from __future__ import annotations

from typing import Any

from langchain_core.documents import Document as LCDocument
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import api_error
from app.core.pagination import encode_cursor, paginate
from app.models import ChunkItem, ChunkSetVersion, Index, IndexBuild, RetrievalRun, SegmentItem, SegmentSetVersion
from app.schemas.retrieval import RetrieveRequest, RetrieveResponse, RetrievedDocument, VectorConfig
from app.storage.object_store import object_store
from app.storage.qdrant import get_qdrant_client


class RetrievalService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def retrieve(self, project_id: str, request: RetrieveRequest) -> RetrieveResponse:
        strategy_type = request.strategy.type
        docs: list[LCDocument] = []

        base_strategy_type = request.strategy.base.get("type", "bm25") if strategy_type == "rerank" else None
        should_load_unindexed_docs = strategy_type in {"bm25", "regex", "fuzzy", "ensemble"} or (
            strategy_type == "rerank" and base_strategy_type != "vector"
        )

        if should_load_unindexed_docs:
            docs = await self._load_unindexed_docs(project_id, request.target, request.target_id)

        if strategy_type == "bm25":
            docs = self._run_bm25(docs, request.query, request.strategy.k)
        elif strategy_type == "regex":
            docs = self._run_regex(docs, request.strategy.pattern)
        elif strategy_type == "fuzzy":
            docs = self._run_fuzzy(docs, request.query, request.strategy.threshold)
        elif strategy_type == "vector":
            docs = await self._run_vector(project_id, request)
        elif strategy_type == "ensemble":
            docs = self._run_ensemble(docs, request.query, request.strategy.sources, request.strategy.weights)
        elif strategy_type == "rerank":
            docs = await self._run_rerank(project_id, request, docs)
        elif strategy_type == "dual_storage":
            docs = await self._run_dual_storage(project_id, request, docs)
        elif strategy_type == "graph":
            docs = await self._run_graph(request)
        elif strategy_type == "graph_hybrid":
            docs = await self._run_graph_hybrid(project_id, request)
        else:
            raise api_error(400, "unsupported_strategy", "Unsupported retrieval strategy", {"strategy": strategy_type})

        page = paginate(request.limit, request.cursor, settings.page_size_default, settings.page_size_max)
        total = len(docs)
        sliced = docs[page.offset : page.offset + page.limit]
        next_offset = page.offset + page.limit if page.offset + page.limit < total else None

        items = [RetrievedDocument(page_content=d.page_content, metadata=d.metadata, score=d.metadata.get("score")) for d in sliced]

        run_id = None
        if request.persist:
            run = RetrievalRun(
                project_id=project_id,
                strategy=strategy_type,
                query=request.query,
                target_type=request.target,
                target_id=request.target_id,
                params_json=request.model_dump(mode="json"),
                results_json={
                    "items": [i.model_dump() for i in items],
                    "total": total,
                    "next_cursor": encode_cursor(next_offset),
                },
                artifact_uri=None,
            )
            self.session.add(run)
            await self.session.commit()
            await self.session.refresh(run)
            run_id = run.run_id

            key = f"projects/{project_id}/retrieval_runs/{run.run_id}/result.json"
            uri = object_store.put_json(key, run.results_json)
            run.artifact_uri = uri
            await self.session.commit()

        return RetrieveResponse(
            items=items,
            next_cursor=encode_cursor(next_offset),
            has_more=next_offset is not None,
            strategy=strategy_type,
            target=request.target,
            target_id=request.target_id,
            total=total,
            run_id=run_id,
        )

    async def _load_unindexed_docs(self, project_id: str, target: str, target_id: str | None) -> list[LCDocument]:
        if target == "chunk_set":
            chunk_set_id = target_id or await self._latest_active_chunk_set(project_id)
            stmt = (
                select(ChunkItem)
                .where(ChunkItem.chunk_set_version_id == chunk_set_id)
                .order_by(ChunkItem.position.asc())
            )
            res = await self.session.execute(stmt)
            rows = res.scalars().all()
            return [
                LCDocument(
                    page_content=r.content,
                    metadata={
                        "item_id": r.item_id,
                        "position": r.position,
                        "chunk_set_version_id": r.chunk_set_version_id,
                        **(r.metadata_json or {}),
                    },
                )
                for r in rows
            ]

        if target == "segment_set":
            seg_set_id = target_id or await self._latest_active_segment_set(project_id)
            stmt = (
                select(SegmentItem)
                .where(SegmentItem.segment_set_version_id == seg_set_id)
                .order_by(SegmentItem.position.asc())
            )
            res = await self.session.execute(stmt)
            rows = res.scalars().all()
            return [
                LCDocument(
                    page_content=r.content,
                    metadata={
                        "item_id": r.item_id,
                        "position": r.position,
                        "segment_set_version_id": r.segment_set_version_id,
                        **(r.metadata_json or {}),
                    },
                )
                for r in rows
            ]

        raise api_error(400, "unsupported_target", "Unindexed retrieval target must be chunk_set or segment_set", {"target": target})

    async def _run_vector(self, project_id: str, request: RetrieveRequest) -> list[LCDocument]:
        if request.target != "index_build":
            raise api_error(400, "invalid_target", "Vector strategy requires target=index_build", {"target": request.target})
        if not request.target_id:
            raise api_error(400, "missing_target_id", "target_id is required for vector retrieval")

        build = await self.session.get(IndexBuild, request.target_id)
        if not build or build.project_id != project_id or build.is_deleted:
            raise api_error(404, "index_build_not_found", "Index build not found", {"build_id": request.target_id})

        index_row = await self.session.get(Index, build.index_id)
        if not index_row or index_row.is_deleted:
            raise api_error(404, "index_not_found", "Index not found", {"index_id": build.index_id})
        provider = index_row.provider.lower()
        if provider not in {"qdrant", "faiss", "chroma", "postgres"}:
            raise api_error(501, "provider_unsupported", "Provider is not implemented", {"provider": provider})

        if provider == "faiss":
            return self._run_vector_faiss(index_row=index_row, query=request.query, k=request.strategy.k)
        if provider == "chroma":
            return self._run_vector_chroma(index_row=index_row, query=request.query, k=request.strategy.k)
        if provider == "postgres":
            return self._run_vector_postgres(index_row=index_row, query=request.query, k=request.strategy.k)

        collection = index_row.config_json.get(
            "collection_name",
            f"{settings.default_vector_collection_prefix}_{index_row.project_id}_{index_row.index_id}",
        )

        query_vector = self._embed_query(index_row, request.query)
        qdrant = get_qdrant_client()
        k = request.strategy.k
        scored = qdrant.search(collection_name=collection, query_vector=query_vector, limit=k, with_payload=True)

        docs: list[LCDocument] = []
        for hit in scored:
            payload = hit.payload or {}
            metadata = payload.get("metadata", {})
            metadata["score"] = float(hit.score)
            metadata["chunk_item_id"] = payload.get("chunk_item_id")
            metadata["chunk_set_version_id"] = payload.get("chunk_set_version_id")
            docs.append(LCDocument(page_content=payload.get("content", ""), metadata=metadata))
        return docs

    def _run_vector_faiss(self, index_row: Index, query: str, k: int) -> list[LCDocument]:
        faiss_dir = index_row.config_json.get("faiss_local_dir")
        if not faiss_dir:
            raise api_error(500, "missing_faiss_artifact", "FAISS index path is missing from index configuration", {"index_id": index_row.index_id})

        try:
            from langchain_community.vectorstores import FAISS
        except Exception:
            raise api_error(424, "missing_dependency", "FAISS runtime dependencies are not available", {"provider": "faiss"})

        embeddings = self._get_embeddings(index_row)
        store = FAISS.load_local(faiss_dir, embeddings, allow_dangerous_deserialization=True)
        scored = store.similarity_search_with_score(query=query, k=k)

        docs: list[LCDocument] = []
        for doc, score in scored:
            metadata = dict(doc.metadata or {})
            metadata["score"] = float(score)
            docs.append(LCDocument(page_content=doc.page_content, metadata=metadata))
        return docs

    def _run_vector_chroma(self, index_row: Index, query: str, k: int) -> list[LCDocument]:
        persist_directory = index_row.config_json.get("chroma_persist_directory")
        collection_name = index_row.config_json.get("collection_name")
        if not persist_directory or not collection_name:
            raise api_error(500, "missing_chroma_artifact", "Chroma index configuration is incomplete", {"index_id": index_row.index_id})

        try:
            from langchain_chroma import Chroma
        except Exception:
            raise api_error(424, "missing_dependency", "Chroma runtime dependency is not available", {"provider": "chroma"})

        embeddings = self._get_embeddings(index_row)
        store = Chroma(collection_name=collection_name, embedding_function=embeddings, persist_directory=persist_directory)
        scored = store.similarity_search_with_score(query=query, k=k)

        docs: list[LCDocument] = []
        for doc, score in scored:
            metadata = dict(doc.metadata or {})
            metadata["score"] = float(score)
            docs.append(LCDocument(page_content=doc.page_content, metadata=metadata))
        return docs

    def _run_vector_postgres(self, index_row: Index, query: str, k: int) -> list[LCDocument]:
        collection_name = index_row.config_json.get("collection_name")
        connection = index_row.config_json.get("connection") or settings.vector_postgres_connection
        if not collection_name or not connection:
            raise api_error(500, "missing_pgvector_config", "Postgres vector configuration is incomplete", {"index_id": index_row.index_id})

        try:
            from langchain_postgres import PGVector
        except Exception:
            raise api_error(424, "missing_dependency", "PGVector runtime dependency is not available", {"provider": "postgres"})

        embeddings = self._get_embeddings(index_row)
        store = PGVector(embeddings=embeddings, collection_name=collection_name, connection=connection, use_jsonb=True)
        scored = store.similarity_search_with_score(query=query, k=k)

        docs: list[LCDocument] = []
        for doc, score in scored:
            metadata = dict(doc.metadata or {})
            metadata["score"] = float(score)
            docs.append(LCDocument(page_content=doc.page_content, metadata=metadata))
        return docs

    def _get_embeddings(self, index_row: Index):
        provider = index_row.config_json.get("embedding_provider", "mock")
        model_name = index_row.config_json.get("embedding_model_name")
        if provider == "mock":
            from rag_lib.embeddings.mock import MockEmbeddings

            return MockEmbeddings()

        from rag_lib.embeddings.factory import get_embeddings_model

        return get_embeddings_model(provider=provider, model_name=model_name)

    def _embed_query(self, index_row: Index, query: str) -> list[float]:
        return self._get_embeddings(index_row).embed_query(query)

    def _run_bm25(self, docs: list[LCDocument], query: str, k: int) -> list[LCDocument]:
        try:
            from rag_lib.retrieval.retrievers import get_bm25_retriever

            retriever = get_bm25_retriever(docs, k=k)
            return list(retriever.invoke(query))
        except Exception:
            # Fallback when rank_bm25 is not installed.
            q_tokens = {t for t in query.lower().split() if t}
            scored = []
            for doc in docs:
                tokens = set(doc.page_content.lower().split())
                score = len(q_tokens.intersection(tokens))
                if score > 0:
                    enriched = LCDocument(page_content=doc.page_content, metadata={**doc.metadata, "score": float(score)})
                    scored.append((score, enriched))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [d for _, d in scored[:k]]

    def _run_regex(self, docs: list[LCDocument], pattern: str) -> list[LCDocument]:
        from rag_lib.retrieval.retrievers import RegexRetriever

        retriever = RegexRetriever(documents=docs)
        return list(retriever.invoke(pattern))

    def _run_fuzzy(self, docs: list[LCDocument], query: str, threshold: int) -> list[LCDocument]:
        from rag_lib.retrieval.retrievers import FuzzyRetriever

        retriever = FuzzyRetriever(documents=docs, threshold=threshold)
        return list(retriever.invoke(query))

    def _run_ensemble(self, docs: list[LCDocument], query: str, sources: list[dict[str, Any]], weights: list[float] | None):
        from rag_lib.retrieval.composition import create_ensemble_retriever
        from rag_lib.retrieval.retrievers import FuzzyRetriever, RegexRetriever

        retrievers = []
        if not sources:
            try:
                from rag_lib.retrieval.retrievers import get_bm25_retriever

                retrievers.append(get_bm25_retriever(docs, k=8))
            except Exception:
                pass
            retrievers.extend([RegexRetriever(documents=docs), FuzzyRetriever(documents=docs, threshold=75)])
        else:
            for src in sources:
                st = src.get("type")
                if st == "bm25":
                    try:
                        from rag_lib.retrieval.retrievers import get_bm25_retriever

                        retrievers.append(get_bm25_retriever(docs, k=src.get("k", 8)))
                    except Exception:
                        continue
                elif st == "regex":
                    retrievers.append(RegexRetriever(documents=docs))
                elif st == "fuzzy":
                    retrievers.append(FuzzyRetriever(documents=docs, threshold=src.get("threshold", 75)))

        if not retrievers:
            raise api_error(400, "invalid_ensemble_sources", "No valid ensemble sources")

        ensemble = create_ensemble_retriever(retrievers, weights=weights)
        return list(ensemble.invoke(query))

    async def _run_rerank(self, project_id: str, request: RetrieveRequest, docs: list[LCDocument]) -> list[LCDocument]:
        base_spec = request.strategy.base or {}
        base_type = base_spec.get("type", "bm25")
        if base_type == "vector":
            # Build a synthetic request for vector search.
            vector_req = request.model_copy(deep=True)
            vector_req.strategy = VectorConfig(**base_spec)
            return await self._run_vector(project_id, vector_req)

        if base_type == "regex":
            base_docs = self._run_regex(docs, base_spec.get("pattern", request.query))
        elif base_type == "fuzzy":
            base_docs = self._run_fuzzy(docs, request.query, int(base_spec.get("threshold", 75)))
        else:
            base_docs = self._run_bm25(docs, request.query, int(base_spec.get("k", 20)))

        from rag_lib.retrieval.composition import create_reranking_retriever
        from rag_lib.retrieval.retrievers import get_bm25_retriever

        # Wrap base docs into a retriever for reranking.
        base_retriever = get_bm25_retriever(base_docs, k=len(base_docs) or 1)
        reranked = create_reranking_retriever(
            base_retriever_or_list=base_retriever,
            reranker_model=request.strategy.model_name,
            top_n=request.strategy.top_n,
            device=request.strategy.device,
        )
        return list(reranked.invoke(request.query))

    async def _run_dual_storage(self, project_id: str, request: RetrieveRequest, docs: list[LCDocument]) -> list[LCDocument]:
        if request.target != "index_build" or not request.target_id:
            raise api_error(400, "invalid_target", "dual_storage requires target=index_build and target_id")

        build = await self.session.get(IndexBuild, request.target_id)
        if not build:
            raise api_error(404, "index_build_not_found", "Index build not found")

        index_row = await self.session.get(Index, build.index_id)
        if not index_row:
            raise api_error(404, "index_not_found", "Index not found")

        if index_row.provider.lower() != "qdrant":
            raise api_error(501, "provider_unsupported", "dual_storage currently supports qdrant-backed builds")

        # 1) Vector recall ids from qdrant.
        collection = index_row.config_json.get(
            "collection_name",
            f"{settings.default_vector_collection_prefix}_{index_row.project_id}_{index_row.index_id}",
        )
        query_vector = self._embed_query(index_row, request.query)
        qdrant = get_qdrant_client()
        hits = qdrant.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=request.strategy.vector_search.get("k", 10),
            with_payload=True,
        )
        ids = [str(h.payload.get("chunk_item_id")) for h in hits if h.payload and h.payload.get("chunk_item_id")]

        # 2) Hydrate from chunk store (full docs).
        if not ids:
            return []

        stmt = select(ChunkItem).where(
            ChunkItem.chunk_set_version_id == build.chunk_set_version_id,
            ChunkItem.item_id.in_(ids),
        )
        res = await self.session.execute(stmt)
        rows = res.scalars().all()
        by_id = {r.item_id: r for r in rows}

        out: list[LCDocument] = []
        for hit in hits:
            payload = hit.payload or {}
            item_id = str(payload.get("chunk_item_id"))
            row = by_id.get(item_id)
            if not row:
                continue
            out.append(
                LCDocument(
                    page_content=row.content,
                    metadata={
                        **(row.metadata_json or {}),
                        "score": float(hit.score),
                        "item_id": row.item_id,
                        "chunk_set_version_id": row.chunk_set_version_id,
                    },
                )
            )
        return out

    async def _run_graph(self, request: RetrieveRequest) -> list[LCDocument]:
        from app.services.graph_service import GraphService

        svc = GraphService(self.session)
        docs = await svc.query_graph(
            graph_build_id=request.strategy.graph_build_id,
            query=request.query,
            mode=request.strategy.mode,
            search_depth=request.strategy.search_depth,
        )
        return list(docs)

    async def _run_graph_hybrid(self, project_id: str, request: RetrieveRequest) -> list[LCDocument]:
        graph_docs = await self._run_graph(request)

        # Reuse vector retrieval path if caller provided an index_build target.
        vector_docs: list[LCDocument] = []
        vector_spec = request.strategy.vector or {}
        if request.target == "index_build" and request.target_id:
            vector_req = request.model_copy(deep=True)
            vector_req.strategy = VectorConfig(
                k=int(vector_spec.get("k", 10)),
                search_type=vector_spec.get("search_type", "similarity"),
                score_threshold=vector_spec.get("score_threshold"),
            )
            vector_docs = await self._run_vector(project_id, vector_req)

        merged = self._merge_scored_lists(
            vector_docs,
            graph_docs,
            request.strategy.weights or [0.7, 0.3],
        )
        return merged

    def _merge_scored_lists(
        self,
        vector_docs: list[LCDocument],
        graph_docs: list[LCDocument],
        weights: list[float],
    ) -> list[LCDocument]:
        vector_weight = weights[0] if len(weights) > 0 else 0.7
        graph_weight = weights[1] if len(weights) > 1 else 0.3

        scores: dict[str, tuple[LCDocument, float]] = {}

        for rank, doc in enumerate(vector_docs):
            key = doc.metadata.get("item_id") or doc.metadata.get("chunk_item_id") or doc.page_content
            score = vector_weight * (1.0 / (rank + 1))
            existing = scores.get(key)
            if existing:
                scores[key] = (existing[0], existing[1] + score)
            else:
                scores[key] = (doc, score)

        for rank, doc in enumerate(graph_docs):
            key = doc.metadata.get("node_id") or doc.page_content
            score = graph_weight * (1.0 / (rank + 1))
            existing = scores.get(key)
            if existing:
                scores[key] = (existing[0], existing[1] + score)
            else:
                scores[key] = (doc, score)

        ranked = sorted(scores.values(), key=lambda item: item[1], reverse=True)
        out: list[LCDocument] = []
        for doc, score in ranked:
            meta = dict(doc.metadata or {})
            meta["score"] = float(score)
            out.append(LCDocument(page_content=doc.page_content, metadata=meta))
        return out

    async def _latest_active_chunk_set(self, project_id: str) -> str:
        stmt = (
            select(ChunkSetVersion)
            .where(
                ChunkSetVersion.project_id == project_id,
                ChunkSetVersion.is_active.is_(True),
                ChunkSetVersion.is_deleted.is_(False),
            )
            .order_by(ChunkSetVersion.created_at.desc())
        )
        res = await self.session.execute(stmt)
        row = res.scalars().first()
        if not row:
            raise api_error(404, "chunk_set_not_found", "No active chunk set found for project", {"project_id": project_id})
        return row.chunk_set_version_id

    async def _latest_active_segment_set(self, project_id: str) -> str:
        stmt = (
            select(SegmentSetVersion)
            .where(
                SegmentSetVersion.project_id == project_id,
                SegmentSetVersion.is_active.is_(True),
                SegmentSetVersion.is_deleted.is_(False),
            )
            .order_by(SegmentSetVersion.created_at.desc())
        )
        res = await self.session.execute(stmt)
        row = res.scalars().first()
        if not row:
            raise api_error(404, "segment_set_not_found", "No active segment set found for project", {"project_id": project_id})
        return row.segment_set_version_id

    async def list_runs(self, project_id: str) -> list[RetrievalRun]:
        stmt = (
            select(RetrievalRun)
            .where(RetrievalRun.project_id == project_id, RetrievalRun.is_deleted.is_(False))
            .order_by(RetrievalRun.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_run(self, run_id: str) -> RetrievalRun:
        row = await self.session.get(RetrievalRun, run_id)
        if not row or row.is_deleted:
            raise api_error(404, "retrieval_run_not_found", "Retrieval run not found", {"run_id": run_id})
        return row

    async def soft_delete_run(self, run_id: str) -> RetrievalRun:
        row = await self.get_run(run_id)
        row.is_deleted = True
        await self.session.commit()
        await self.session.refresh(row)
        return row
