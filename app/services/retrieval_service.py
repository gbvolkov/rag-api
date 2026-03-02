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
from app.storage.keys import uri_to_key
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
            docs = self._run_fuzzy(docs, request.query, request.strategy.threshold, request.strategy.mode)
        elif strategy_type == "vector":
            docs = await self._run_vector(project_id, request)
        elif strategy_type == "ensemble":
            docs = await self._run_ensemble(project_id, request, docs)
        elif strategy_type == "rerank":
            docs = await self._run_rerank(project_id, request, docs)
        elif strategy_type == "dual_storage":
            docs = await self._run_dual_storage(project_id, request, docs)
        elif strategy_type == "graph":
            docs = await self._run_graph(project_id, request)
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
        if target in {"chunk_set", "index_build"}:
            if target == "chunk_set":
                chunk_set_id = target_id or await self._latest_active_chunk_set(project_id)
            else:
                if not target_id:
                    raise api_error(400, "missing_target_id", "target_id is required for target=index_build")
                build = await self.session.get(IndexBuild, target_id)
                if not build or build.project_id != project_id or build.is_deleted:
                    raise api_error(404, "index_build_not_found", "Index build not found", {"build_id": target_id})
                chunk_set_id = build.chunk_set_version_id

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

        raise api_error(400, "unsupported_target", "Unindexed retrieval target must be chunk_set, segment_set, or index_build", {"target": target})

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
            return self._run_vector_faiss(
                index_row=index_row,
                query=request.query,
                k=request.strategy.k,
                search_type=request.strategy.search_type,
                score_threshold=request.strategy.score_threshold,
                metadata_filter=request.strategy.filter,
            )
        if provider == "chroma":
            return self._run_vector_chroma(
                index_row=index_row,
                query=request.query,
                k=request.strategy.k,
                search_type=request.strategy.search_type,
                score_threshold=request.strategy.score_threshold,
                metadata_filter=request.strategy.filter,
            )
        if provider == "postgres":
            return self._run_vector_postgres(
                index_row=index_row,
                query=request.query,
                k=request.strategy.k,
                search_type=request.strategy.search_type,
                score_threshold=request.strategy.score_threshold,
                metadata_filter=request.strategy.filter,
            )

        collection = index_row.config_json.get(
            "collection_name",
            f"{settings.default_vector_collection_prefix}_{index_row.project_id}_{index_row.index_id}",
        )

        query_vector = self._embed_query(index_row, request.query)
        qdrant = get_qdrant_client()
        k = request.strategy.k
        if request.strategy.search_type == "mmr":
            raise api_error(
                501,
                "provider_unsupported",
                "mmr search_type is not supported for qdrant retrieval via this API path",
                {"provider": "qdrant", "search_type": "mmr"},
            )
        try:
            scored = qdrant.query_points(
                collection_name=collection,
                query=query_vector,
                limit=k,
                with_payload=True,
            ).points
        except Exception as exc:
            raise api_error(
                424,
                "qdrant_unavailable",
                "Qdrant request failed",
                {"qdrant_url": settings.qdrant_url, "error": str(exc)},
                hint="Start Qdrant and verify QDRANT_URL is reachable from rag-api.",
            ) from exc

        docs: list[LCDocument] = []
        for hit in scored:
            payload = hit.payload or {}
            metadata = payload.get("metadata", {})
            metadata["score"] = float(hit.score)
            metadata["chunk_item_id"] = payload.get("chunk_item_id")
            metadata["chunk_set_version_id"] = payload.get("chunk_set_version_id")
            if request.strategy.search_type == "similarity_score_threshold" and request.strategy.score_threshold is not None:
                if float(hit.score) < float(request.strategy.score_threshold):
                    continue
            docs.append(LCDocument(page_content=payload.get("content", ""), metadata=metadata))
        return docs

    def _run_vector_faiss(
        self,
        index_row: Index,
        query: str,
        k: int,
        search_type: str,
        score_threshold: float | None,
        metadata_filter: dict[str, Any] | None,
    ) -> list[LCDocument]:
        faiss_dir = index_row.config_json.get("faiss_local_dir")
        if not faiss_dir:
            raise api_error(500, "missing_faiss_artifact", "FAISS index path is missing from index configuration", {"index_id": index_row.index_id})

        try:
            from langchain_community.vectorstores import FAISS
        except Exception:
            raise api_error(424, "missing_dependency", "FAISS runtime dependencies are not available", {"provider": "faiss"})

        embeddings = self._get_embeddings(index_row)
        store = FAISS.load_local(faiss_dir, embeddings, allow_dangerous_deserialization=True)
        return self._invoke_vector_store(
            store,
            query=query,
            k=k,
            search_type=search_type,
            score_threshold=score_threshold,
            metadata_filter=metadata_filter,
        )

    def _run_vector_chroma(
        self,
        index_row: Index,
        query: str,
        k: int,
        search_type: str,
        score_threshold: float | None,
        metadata_filter: dict[str, Any] | None,
    ) -> list[LCDocument]:
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
        return self._invoke_vector_store(
            store,
            query=query,
            k=k,
            search_type=search_type,
            score_threshold=score_threshold,
            metadata_filter=metadata_filter,
        )

    def _run_vector_postgres(
        self,
        index_row: Index,
        query: str,
        k: int,
        search_type: str,
        score_threshold: float | None,
        metadata_filter: dict[str, Any] | None,
    ) -> list[LCDocument]:
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
        return self._invoke_vector_store(
            store,
            query=query,
            k=k,
            search_type=search_type,
            score_threshold=score_threshold,
            metadata_filter=metadata_filter,
        )

    def _get_embeddings(self, index_row: Index):
        provider = index_row.config_json.get("embedding_provider", "mock")
        model_name = index_row.config_json.get("embedding_model_name")
        if provider == "mock":
            from rag_lib.embeddings.mock import MockEmbeddings

            return MockEmbeddings()

        from rag_lib.embeddings.factory import create_embeddings_model

        return create_embeddings_model(provider=provider, model_name=model_name)

    def _embed_query(self, index_row: Index, query: str) -> list[float]:
        return self._get_embeddings(index_row).embed_query(query)

    def _invoke_vector_store(
        self,
        vector_store: Any,
        *,
        query: str,
        k: int,
        search_type: str,
        score_threshold: float | None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[LCDocument]:
        search_kwargs: dict[str, Any] = {"k": k}
        if score_threshold is not None:
            search_kwargs["score_threshold"] = score_threshold
        if metadata_filter:
            search_kwargs["filter"] = metadata_filter
        retriever = vector_store.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs,
        )
        return list(retriever.invoke(query))

    def _load_materialized_vector_store(self, index_row: Index):
        provider = index_row.provider.lower()
        embeddings = self._get_embeddings(index_row)

        if provider == "faiss":
            faiss_dir = index_row.config_json.get("faiss_local_dir")
            if not faiss_dir:
                raise api_error(
                    500,
                    "missing_faiss_artifact",
                    "FAISS index path is missing from index configuration",
                    {"index_id": index_row.index_id},
                )
            try:
                from langchain_community.vectorstores import FAISS
            except Exception:
                raise api_error(424, "missing_dependency", "FAISS runtime dependencies are not available", {"provider": "faiss"})
            return FAISS.load_local(faiss_dir, embeddings, allow_dangerous_deserialization=True)

        if provider == "chroma":
            persist_directory = index_row.config_json.get("chroma_persist_directory")
            collection_name = index_row.config_json.get("collection_name")
            if not persist_directory or not collection_name:
                raise api_error(
                    500,
                    "missing_chroma_artifact",
                    "Chroma index configuration is incomplete",
                    {"index_id": index_row.index_id},
                )
            try:
                from langchain_chroma import Chroma
            except Exception:
                raise api_error(424, "missing_dependency", "Chroma runtime dependency is not available", {"provider": "chroma"})
            return Chroma(collection_name=collection_name, embedding_function=embeddings, persist_directory=persist_directory)

        if provider == "postgres":
            collection_name = index_row.config_json.get("collection_name")
            connection = index_row.config_json.get("connection") or settings.vector_postgres_connection
            if not collection_name or not connection:
                raise api_error(
                    500,
                    "missing_pgvector_config",
                    "Postgres vector configuration is incomplete",
                    {"index_id": index_row.index_id},
                )
            try:
                from langchain_postgres import PGVector
            except Exception:
                raise api_error(424, "missing_dependency", "PGVector runtime dependency is not available", {"provider": "postgres"})
            return PGVector(embeddings=embeddings, collection_name=collection_name, connection=connection, use_jsonb=True)

        raise api_error(501, "provider_unsupported", "Provider is not implemented", {"provider": provider})

    def _run_bm25(self, docs: list[LCDocument], query: str, k: int) -> list[LCDocument]:
        try:
            from rag_lib.retrieval.retrievers import create_bm25_retriever

            retriever = create_bm25_retriever(docs, top_k=k)
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

    def _run_fuzzy(self, docs: list[LCDocument], query: str, threshold: int, mode: str = "partial_ratio") -> list[LCDocument]:
        from rag_lib.retrieval.retrievers import FuzzyRetriever

        retriever = FuzzyRetriever(documents=docs, threshold=threshold, mode=mode)
        return list(retriever.invoke(query))

    async def _run_ensemble(self, project_id: str, request: RetrieveRequest, docs: list[LCDocument]):
        from rag_lib.retrieval.composition import create_ensemble_retriever
        from rag_lib.retrieval.retrievers import FuzzyRetriever, RegexRetriever, create_vector_retriever

        retrievers = []
        sources = request.strategy.sources
        weights = request.strategy.weights
        if not sources:
            try:
                from rag_lib.retrieval.retrievers import create_bm25_retriever

                retrievers.append(create_bm25_retriever(docs, top_k=8))
            except Exception:
                pass
            retrievers.extend([RegexRetriever(documents=docs), FuzzyRetriever(documents=docs, threshold=75)])
        else:
            for src in sources:
                st = src.get("type")
                if st == "bm25":
                    try:
                        from rag_lib.retrieval.retrievers import create_bm25_retriever

                        retrievers.append(create_bm25_retriever(docs, top_k=src.get("k", 8)))
                    except Exception:
                        continue
                elif st == "regex":
                    retrievers.append(RegexRetriever(documents=docs))
                elif st == "fuzzy":
                    retrievers.append(
                        FuzzyRetriever(
                            documents=docs,
                            threshold=src.get("threshold", 75),
                            mode=src.get("mode", "partial_ratio"),
                        )
                    )
                elif st == "vector":
                    if request.target != "index_build" or not request.target_id:
                        continue
                    build = await self.session.get(IndexBuild, request.target_id)
                    index_row = await self.session.get(Index, build.index_id) if build else None
                    if not build or not index_row:
                        continue
                    if index_row.provider.lower() == "qdrant":
                        vector_req = request.model_copy(deep=True)
                        vector_req.strategy = VectorConfig(
                            k=int(src.get("k", 8)),
                            search_type=src.get("search_type", "similarity"),
                            score_threshold=src.get("score_threshold"),
                            filter=src.get("filter"),
                        )
                        vector_docs = await self._run_vector(project_id, vector_req)
                        try:
                            from rag_lib.retrieval.retrievers import create_bm25_retriever

                            retrievers.append(create_bm25_retriever(vector_docs, top_k=src.get("k", 8)))
                        except Exception:
                            continue
                    else:
                        vector_store = self._load_materialized_vector_store(index_row)
                        retrievers.append(
                            create_vector_retriever(
                                vector_store=vector_store,
                                top_k=int(src.get("k", 8)),
                                search_type=src.get("search_type", "similarity"),
                                score_threshold=src.get("score_threshold"),
                            )
                        )

        if not retrievers:
            raise api_error(400, "invalid_ensemble_sources", "No valid ensemble sources")

        ensemble = create_ensemble_retriever(retrievers, weights=weights)
        return list(ensemble.invoke(request.query))

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
            base_docs = self._run_fuzzy(
                docs,
                request.query,
                int(base_spec.get("threshold", 75)),
                base_spec.get("mode", "partial_ratio"),
            )
        else:
            base_docs = self._run_bm25(docs, request.query, int(base_spec.get("k", 20)))

        from rag_lib.retrieval.composition import create_reranking_retriever
        from rag_lib.retrieval.retrievers import create_bm25_retriever

        # Wrap base docs into a retriever for reranking.
        base_retriever = create_bm25_retriever(base_docs, top_k=len(base_docs) or 1)
        reranked = create_reranking_retriever(
            base_retriever_or_list=base_retriever,
            reranker_model=request.strategy.model_name,
            top_k=request.strategy.top_k,
            max_score_ratio=request.strategy.max_score_ratio,
            device=request.strategy.device,
        )
        return list(reranked.invoke(request.query))

    async def _run_dual_storage(self, project_id: str, request: RetrieveRequest, docs: list[LCDocument]) -> list[LCDocument]:
        if request.target != "index_build" or not request.target_id:
            raise api_error(400, "invalid_target", "dual_storage requires target=index_build and target_id")

        build = await self.session.get(IndexBuild, request.target_id)
        if not build or build.project_id != project_id or build.is_deleted:
            raise api_error(404, "index_build_not_found", "Index build not found", {"build_id": request.target_id})
        if build.status != "succeeded":
            raise api_error(
                409,
                "index_build_not_ready",
                "Index build is not ready for dual storage retrieval",
                {"build_id": build.build_id, "status": build.status},
            )

        index_row = await self.session.get(Index, build.index_id)
        if not index_row or index_row.is_deleted:
            raise api_error(404, "index_not_found", "Index not found", {"index_id": build.index_id})

        id_key = request.strategy.id_key
        parent_docs_by_id = self._load_dual_storage_doc_store(build, id_key)

        provider = index_row.provider.lower()
        if provider != "qdrant":
            from langchain_core.stores import InMemoryStore
            from rag_lib.retrieval.composition import create_scored_dual_storage_retriever
            from rag_lib.retrieval.scored_retriever import HydrationMode, SearchType

            search_kwargs = dict(request.strategy.search_kwargs or {})
            search_kwargs.update(request.strategy.vector_search or {})
            if "k" not in search_kwargs:
                search_kwargs["k"] = 10

            doc_store = InMemoryStore()
            doc_store.mset([(item_id, parent_doc) for item_id, parent_doc in parent_docs_by_id.items()])

            vector_store = self._load_materialized_vector_store(index_row)
            retriever = create_scored_dual_storage_retriever(
                vector_store=vector_store,
                doc_store=doc_store,
                id_key=id_key,
                search_kwargs=search_kwargs,
                search_type=SearchType(request.strategy.search_type),
                score_threshold=request.strategy.score_threshold,
                hydration_mode=HydrationMode(request.strategy.hydration_mode),
                enrichment_separator=request.strategy.enrichment_separator,
            )
            return list(retriever.invoke(request.query))

        collection = index_row.config_json.get(
            "collection_name",
            f"{settings.default_vector_collection_prefix}_{index_row.project_id}_{index_row.index_id}",
        )
        query_vector = self._embed_query(index_row, request.query)
        qdrant = get_qdrant_client()
        vector_k = int((request.strategy.vector_search or {}).get("k", 10))

        try:
            hits = qdrant.query_points(
                collection_name=collection,
                query=query_vector,
                limit=vector_k,
                with_payload=True,
            ).points
        except Exception as exc:
            raise api_error(
                424,
                "qdrant_unavailable",
                "Qdrant request failed",
                {"qdrant_url": settings.qdrant_url, "error": str(exc)},
                hint="Start Qdrant and verify QDRANT_URL is reachable from rag-api.",
            ) from exc

        if request.strategy.search_type == "similarity_score_threshold" and request.strategy.score_threshold is not None:
            hits = [h for h in hits if float(h.score) >= float(request.strategy.score_threshold)]

        chunk_ids = [str(h.payload.get("chunk_item_id")) for h in hits if h.payload and h.payload.get("chunk_item_id")]
        if not chunk_ids:
            return []

        chunk_stmt = select(ChunkItem).where(
            ChunkItem.chunk_set_version_id == build.chunk_set_version_id,
            ChunkItem.item_id.in_(chunk_ids),
        )
        chunk_res = await self.session.execute(chunk_stmt)
        chunk_rows = list(chunk_res.scalars().all())
        chunks_by_id = {row.item_id: row for row in chunk_rows}

        children: list[LCDocument] = []
        ordered_parent_ids: list[str] = []
        seen_parent_ids: set[str] = set()

        for hit in hits:
            payload = hit.payload or {}
            item_id = str(payload.get("chunk_item_id"))
            row = chunks_by_id.get(item_id)
            if not row:
                continue

            meta = {
                **(row.metadata_json or {}),
                "similarity_score": float(hit.score),
                "score": float(hit.score),
                "item_id": row.item_id,
                "chunk_set_version_id": row.chunk_set_version_id,
            }
            parent_id = meta.get(id_key)
            if parent_id is None:
                raise api_error(
                    500,
                    "doc_store_missing_parent_for_hit",
                    "Retrieved chunk does not contain configured dual storage id_key",
                    {"chunk_item_id": row.item_id, "id_key": id_key},
                )
            parent_id = str(parent_id)
            meta[id_key] = parent_id
            if parent_id not in seen_parent_ids:
                seen_parent_ids.add(parent_id)
                ordered_parent_ids.append(parent_id)
            children.append(LCDocument(page_content=row.content, metadata=meta))

        if not children:
            return []

        mode = request.strategy.hydration_mode
        if mode == "children_enriched":
            enriched: list[LCDocument] = []
            separator = request.strategy.enrichment_separator
            for child in children:
                pid = child.metadata.get(id_key)
                if pid is None:
                    raise api_error(500, "doc_store_missing_parent_for_hit", "Retrieved chunk has no parent id", {"id_key": id_key})
                parent_doc = parent_docs_by_id.get(str(pid))
                if parent_doc is None:
                    raise api_error(
                        500,
                        "doc_store_missing_parent_for_hit",
                        "doc_store does not contain parent document for retrieved chunk",
                        {"parent_id": str(pid), "id_key": id_key},
                    )
                enriched_content = f"{child.page_content}{separator}{parent_doc.page_content}"
                enriched.append(LCDocument(page_content=enriched_content, metadata=dict(child.metadata or {})))
            return enriched

        parent_docs: list[LCDocument] = []
        parent_max_score: dict[str, float] = {}
        for child in children:
            pid = child.metadata.get(id_key)
            if pid is None:
                continue
            pid_str = str(pid)
            score = float(child.metadata.get("similarity_score", child.metadata.get("score", 0.0)) or 0.0)
            if pid_str not in parent_max_score or score > parent_max_score[pid_str]:
                parent_max_score[pid_str] = score

        for pid in ordered_parent_ids:
            parent_doc = parent_docs_by_id.get(pid)
            if parent_doc is None:
                raise api_error(
                    500,
                    "doc_store_missing_parent_for_hit",
                    "doc_store does not contain parent document for retrieved chunk",
                    {"parent_id": pid, "id_key": id_key},
                )
            meta = dict(parent_doc.metadata or {})
            meta[id_key] = pid
            meta["similarity_score"] = parent_max_score.get(pid)
            meta["score"] = parent_max_score.get(pid)
            parent_docs.append(LCDocument(page_content=parent_doc.page_content, metadata=meta))

        if mode == "children_plus_parents":
            return children + parent_docs
        return parent_docs

    def _load_index_build_manifest(self, build: IndexBuild) -> dict[str, Any]:
        if not build.artifact_uri:
            raise api_error(
                409,
                "index_build_not_ready",
                "Index build artifact is missing",
                {"build_id": build.build_id, "status": build.status},
            )
        key = uri_to_key(build.artifact_uri)
        try:
            payload = object_store.get_json(key)
        except Exception as exc:
            raise api_error(
                500,
                "missing_index_manifest",
                "Index build manifest could not be loaded",
                {"build_id": build.build_id, "artifact_uri": build.artifact_uri},
            ) from exc
        if not isinstance(payload, dict):
            raise api_error(500, "invalid_index_manifest", "Index build manifest must be a JSON object", {"build_id": build.build_id})
        return payload

    def _load_dual_storage_doc_store(self, build: IndexBuild, id_key: str) -> dict[str, LCDocument]:
        manifest = self._load_index_build_manifest(build)
        doc_store_meta = manifest.get("doc_store")
        if not isinstance(doc_store_meta, dict):
            raise api_error(
                400,
                "doc_store_required_for_dual_storage",
                "dual_storage retrieval requires index build with doc_store",
                {"build_id": build.build_id},
            )

        configured_id_key = doc_store_meta.get("id_key")
        if configured_id_key != id_key:
            raise api_error(
                400,
                "dual_storage_id_key_mismatch",
                "dual_storage id_key does not match index build doc_store id_key",
                {"requested_id_key": id_key, "configured_id_key": configured_id_key},
            )

        artifact_uri = doc_store_meta.get("artifact_uri")
        if not isinstance(artifact_uri, str) or not artifact_uri:
            raise api_error(
                500,
                "missing_doc_store_artifact",
                "doc_store artifact_uri is missing from index build manifest",
                {"build_id": build.build_id},
            )

        key = uri_to_key(artifact_uri)
        try:
            payload = object_store.get_json(key)
        except Exception as exc:
            raise api_error(
                500,
                "missing_doc_store_artifact",
                "doc_store artifact could not be loaded",
                {"build_id": build.build_id, "artifact_uri": artifact_uri},
            ) from exc

        if not isinstance(payload, dict):
            raise api_error(500, "invalid_doc_store_artifact", "doc_store artifact must be a JSON object", {"build_id": build.build_id})

        items = payload.get("items")
        if not isinstance(items, list):
            raise api_error(
                500,
                "invalid_doc_store_artifact",
                "doc_store artifact must contain a list under items",
                {"build_id": build.build_id},
            )

        parent_docs_by_id: dict[str, LCDocument] = {}
        for item in items:
            if not isinstance(item, dict):
                raise api_error(
                    500,
                    "invalid_doc_store_artifact",
                    "doc_store item must be a JSON object",
                    {"build_id": build.build_id},
                )
            parent_id = item.get("id")
            if parent_id is None:
                raise api_error(
                    500,
                    "invalid_doc_store_artifact",
                    "doc_store item must contain id",
                    {"build_id": build.build_id},
                )
            parent_id_str = str(parent_id)
            metadata = item.get("metadata")
            safe_metadata = dict(metadata) if isinstance(metadata, dict) else {}
            safe_metadata[id_key] = parent_id_str
            safe_metadata.setdefault("item_id", parent_id_str)
            parent_docs_by_id[parent_id_str] = LCDocument(
                page_content=str(item.get("page_content", "")),
                metadata=safe_metadata,
            )
        return parent_docs_by_id

    async def _run_graph(self, project_id: str, request: RetrieveRequest) -> list[LCDocument]:
        from app.services.graph_service import GraphService

        svc = GraphService(self.session)
        docs = await svc.query_graph(
            graph_build_id=request.strategy.graph_build_id,
            project_id=project_id,
            query=request.query,
            mode=request.strategy.mode,
            graph_query_config={
                "top_k_entities": request.strategy.top_k_entities,
                "top_k_relations": request.strategy.top_k_relations,
                "top_k_chunks": request.strategy.top_k_chunks,
                "max_hops": request.strategy.max_hops,
                "min_score": request.strategy.min_score,
                "use_rerank": request.strategy.use_rerank,
                "enable_keyword_extraction": request.strategy.enable_keyword_extraction,
                "vector_relevance_mode": request.strategy.vector_relevance_mode,
                "token_budget_total": request.strategy.token_budget_total,
                "token_budget_entities": request.strategy.token_budget_entities,
                "token_budget_relations": request.strategy.token_budget_relations,
                "token_budget_chunks": request.strategy.token_budget_chunks,
            },
        )
        return list(docs)

    async def _run_graph_hybrid(self, project_id: str, request: RetrieveRequest) -> list[LCDocument]:
        graph_docs = await self._run_graph(project_id, request)

        # Reuse vector retrieval path if caller provided an index_build target.
        vector_docs: list[LCDocument] = []
        vector_spec = request.strategy.vector or {}
        if request.target == "index_build" and request.target_id:
            vector_req = request.model_copy(deep=True)
            vector_req.strategy = VectorConfig(
                k=int(vector_spec.get("k", 10)),
                search_type=vector_spec.get("search_type", "similarity"),
                score_threshold=vector_spec.get("score_threshold"),
                filter=vector_spec.get("filter"),
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
