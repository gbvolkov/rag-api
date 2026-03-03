from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.documents import Document as LCDocument
from langchain_core.retrievers import BaseRetriever
from langchain_core.stores import BaseStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import api_error
from app.core.pagination import encode_cursor, paginate
from app.models import Index, IndexBuild, RetrievalRun, SegmentItem
from app.schemas.retrieval import RetrieveRequest, RetrieveResponse, RetrievedDocument
from app.services.vector_store_adapter import create_vector_store_for_retrieval
from app.storage.keys import uri_to_key
from app.storage.object_store import object_store


class _StaticRetriever(BaseRetriever):
    documents: list[LCDocument]

    def _get_relevant_documents(self, query: str, *, run_manager) -> list[LCDocument]:
        return list(self.documents)


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

    async def _load_unindexed_docs(self, project_id: str, target: str, target_id: str) -> list[LCDocument]:
        if target == "index_build":
            build = await self.session.get(IndexBuild, target_id)
            if not build or build.project_id != project_id or build.is_deleted:
                raise api_error(404, "index_build_not_found", "Index build not found", {"build_id": target_id})

            stmt = (
                select(SegmentItem)
                .where(SegmentItem.segment_set_version_id == build.source_set_id)
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

        if target == "segment_set":
            seg_set_id = target_id
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

        raise api_error(400, "unsupported_target", "Unindexed retrieval target must be segment_set or index_build", {"target": target})

    async def _run_vector(self, project_id: str, request: RetrieveRequest) -> list[LCDocument]:
        _, index_row = await self._resolve_index_build(project_id, request.target, request.target_id)
        retriever = self._build_vector_retriever(
            index_row=index_row,
            k=request.strategy.k,
            search_type=request.strategy.search_type,
            score_threshold=request.strategy.score_threshold,
            metadata_filter=request.strategy.filter,
        )
        return list(retriever.invoke(request.query))

    async def _resolve_index_build(self, project_id: str, target: str, target_id: str) -> tuple[IndexBuild, Index]:
        if target != "index_build":
            raise api_error(400, "invalid_target", "Vector-backed strategy requires target=index_build", {"target": target})

        build = await self.session.get(IndexBuild, target_id)
        if not build or build.project_id != project_id or build.is_deleted:
            raise api_error(404, "index_build_not_found", "Index build not found", {"build_id": target_id})
        if build.status != "succeeded":
            raise api_error(
                409,
                "index_build_not_ready",
                "Index build is not ready for retrieval",
                {"build_id": build.build_id, "status": build.status},
            )

        index_row = await self.session.get(Index, build.index_id)
        if not index_row or index_row.is_deleted:
            raise api_error(404, "index_not_found", "Index not found", {"index_id": build.index_id})
        if index_row.provider.lower() not in {"qdrant", "faiss", "chroma", "postgres"}:
            raise api_error(501, "provider_unsupported", "Provider is not implemented", {"provider": index_row.provider})
        return build, index_row

    def _build_vector_retriever(
        self,
        *,
        index_row: Index,
        k: int,
        search_type: str,
        score_threshold: float | None,
        metadata_filter: dict[str, Any] | None,
    ) -> BaseRetriever:
        if metadata_filter:
            raise api_error(
                400,
                "unsupported_strategy_param",
                "strategy.filter is not supported by rag_lib create_vector_retriever",
                {"field": "strategy.filter", "strategy": "vector"},
            )

        from rag_lib.retrieval.retrievers import create_vector_retriever

        vector_store = self._load_materialized_vector_store(index_row)
        try:
            return create_vector_retriever(
                vector_store=vector_store,
                top_k=k,
                search_type=search_type,
                score_threshold=score_threshold,
            )
        except Exception as exc:
            raise api_error(
                400,
                "invalid_vector_strategy",
                "Failed to initialize vector retriever with provided strategy parameters",
                {"search_type": search_type, "score_threshold": score_threshold, "error": str(exc)},
            ) from exc

    def _get_embeddings(self, index_row: Index):
        provider = index_row.config_json.get("embedding_provider", "mock")
        model_name = index_row.config_json.get("embedding_model_name")
        if provider == "mock":
            from rag_lib.embeddings.mock import MockEmbeddings

            return MockEmbeddings()

        from rag_lib.embeddings.factory import create_embeddings_model

        return create_embeddings_model(provider=provider, model_name=model_name)

    def _load_materialized_vector_store(self, index_row: Index):
        embeddings = self._get_embeddings(index_row)
        return create_vector_store_for_retrieval(index_row=index_row, embeddings=embeddings)

    def _run_bm25(self, docs: list[LCDocument], query: str, k: int) -> list[LCDocument]:
        retriever = self._create_bm25_retriever(docs, top_k=k)
        return list(retriever.invoke(query))

    def _create_bm25_retriever(self, docs: list[LCDocument], *, top_k: int) -> BaseRetriever:
        from rag_lib.retrieval.retrievers import create_bm25_retriever

        try:
            return create_bm25_retriever(docs, top_k=top_k)
        except Exception as exc:
            raise api_error(
                424,
                "missing_dependency",
                "BM25 retriever initialization failed",
                {"retriever": "bm25", "error": str(exc)},
            ) from exc

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
        from rag_lib.retrieval.retrievers import FuzzyRetriever, RegexRetriever

        retrievers: list[BaseRetriever] = []
        sources = request.strategy.sources
        weights = request.strategy.weights

        if not sources:
            retrievers.append(self._create_bm25_retriever(docs, top_k=8))
            retrievers.extend([RegexRetriever(documents=docs), FuzzyRetriever(documents=docs, threshold=75)])
        else:
            for src in sources:
                st = src.get("type")
                if st == "bm25":
                    retrievers.append(self._create_bm25_retriever(docs, top_k=int(src.get("k", 8))))
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
                    _, index_row = await self._resolve_index_build(project_id, request.target, request.target_id)
                    retrievers.append(
                        self._build_vector_retriever(
                            index_row=index_row,
                            k=int(src.get("k", 8)),
                            search_type=str(src.get("search_type", "similarity")),
                            score_threshold=src.get("score_threshold"),
                            metadata_filter=src.get("filter"),
                        )
                    )
                else:
                    raise api_error(
                        400,
                        "invalid_ensemble_sources",
                        "Unsupported ensemble source type",
                        {"source_type": st, "allowed": ["bm25", "regex", "fuzzy", "vector"]},
                    )

        if not retrievers:
            raise api_error(400, "invalid_ensemble_sources", "No valid ensemble sources")

        try:
            ensemble = create_ensemble_retriever(retrievers, weights=weights)
        except Exception as exc:
            raise api_error(
                400,
                "invalid_ensemble_sources",
                "Failed to build ensemble retriever",
                {"error": str(exc)},
            ) from exc
        return list(ensemble.invoke(request.query))

    async def _run_rerank(self, project_id: str, request: RetrieveRequest, docs: list[LCDocument]) -> list[LCDocument]:
        base_spec = request.strategy.base or {}
        base_type = base_spec.get("type", "bm25")

        from rag_lib.retrieval.composition import create_reranking_retriever
        from rag_lib.retrieval.retrievers import FuzzyRetriever, RegexRetriever

        if base_type == "vector":
            _, index_row = await self._resolve_index_build(project_id, request.target, request.target_id)
            base_retriever = self._build_vector_retriever(
                index_row=index_row,
                k=int(base_spec.get("k", request.strategy.top_k)),
                search_type=str(base_spec.get("search_type", "similarity")),
                score_threshold=base_spec.get("score_threshold"),
                metadata_filter=base_spec.get("filter"),
            )
        elif base_type == "regex":
            pattern = str(base_spec.get("pattern", request.query))
            if pattern == request.query:
                base_retriever = RegexRetriever(documents=docs)
            else:
                base_retriever = _StaticRetriever(documents=self._run_regex(docs, pattern))
        elif base_type == "fuzzy":
            base_retriever = FuzzyRetriever(
                documents=docs,
                threshold=int(base_spec.get("threshold", 75)),
                mode=str(base_spec.get("mode", "partial_ratio")),
            )
        elif base_type == "bm25":
            base_retriever = self._create_bm25_retriever(docs, top_k=int(base_spec.get("k", 20)))
        else:
            raise api_error(
                400,
                "invalid_rerank_base",
                "Unsupported rerank base strategy",
                {"base_type": base_type, "allowed": ["bm25", "regex", "fuzzy", "vector"]},
            )

        try:
            reranked = create_reranking_retriever(
                base_retriever_or_list=base_retriever,
                reranker_model=request.strategy.model_name,
                top_k=request.strategy.top_k,
                max_score_ratio=request.strategy.max_score_ratio,
                device=request.strategy.device,
            )
        except Exception as exc:
            raise api_error(
                424,
                "missing_dependency",
                "Reranker initialization failed",
                {"error": str(exc), "model_name": request.strategy.model_name},
            ) from exc
        return list(reranked.invoke(request.query))

    async def _run_dual_storage(self, project_id: str, request: RetrieveRequest, docs: list[LCDocument]) -> list[LCDocument]:
        if request.target != "index_build":
            raise api_error(400, "invalid_target", "dual_storage requires target=index_build")

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
        doc_store = self._load_dual_storage_doc_store(build, id_key)
        from rag_lib.retrieval.composition import create_scored_dual_storage_retriever
        from rag_lib.retrieval.scored_retriever import HydrationMode, SearchType

        search_kwargs = dict(request.strategy.search_kwargs or {})
        search_kwargs.update(request.strategy.vector_search or {})
        if "k" not in search_kwargs:
            search_kwargs["k"] = 10

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

    def _load_dual_storage_doc_store(self, build: IndexBuild, id_key: str) -> BaseStore[str, LCDocument]:
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

        backend_raw = doc_store_meta.get("backend")
        if not isinstance(backend_raw, str) or not backend_raw.strip():
            raise api_error(
                500,
                "invalid_doc_store_backend",
                "doc_store backend is missing in index build manifest",
                {"build_id": build.build_id},
            )
        backend = backend_raw.strip().lower()
        if backend not in {"local_file", "redis"}:
            raise api_error(
                500,
                "invalid_doc_store_backend",
                "doc_store backend is invalid in index build manifest",
                {"build_id": build.build_id, "backend": backend_raw},
            )

        artifact_uri = doc_store_meta.get("artifact_uri")
        if not isinstance(artifact_uri, str) or not artifact_uri:
            raise api_error(
                500,
                "missing_doc_store_artifact",
                "doc_store artifact_uri is missing from index build manifest",
                {"build_id": build.build_id},
            )

        if backend == "local_file":
            store_root = Path(artifact_uri)
            if not store_root.exists():
                raise api_error(
                    500,
                    "missing_doc_store_artifact",
                    "doc_store artifact could not be loaded",
                    {"build_id": build.build_id, "artifact_uri": artifact_uri},
                )

            from langchain_classic.storage import LocalFileStore, create_kv_docstore

            byte_store = LocalFileStore(store_root)
            return create_kv_docstore(byte_store)

        redis_namespace_raw = doc_store_meta.get("redis_namespace")
        if not isinstance(redis_namespace_raw, str) or not redis_namespace_raw.strip():
            raise api_error(
                500,
                "missing_doc_store_artifact",
                "doc_store redis_namespace is missing from index build manifest",
                {"build_id": build.build_id},
            )
        redis_namespace = redis_namespace_raw.strip()

        redis_ttl_raw = doc_store_meta.get("redis_ttl")
        try:
            redis_ttl = int(redis_ttl_raw)
        except (TypeError, ValueError) as exc:
            raise api_error(
                500,
                "invalid_doc_store_artifact",
                "doc_store redis_ttl is invalid in index build manifest",
                {"build_id": build.build_id, "redis_ttl": redis_ttl_raw},
            ) from exc
        if redis_ttl <= 0:
            raise api_error(
                500,
                "invalid_doc_store_artifact",
                "doc_store redis_ttl is invalid in index build manifest",
                {"build_id": build.build_id, "redis_ttl": redis_ttl_raw},
            )

        from langchain_classic.storage import RedisStore, create_kv_docstore

        byte_store = RedisStore(redis_url=artifact_uri, namespace=redis_namespace, ttl=redis_ttl)
        return create_kv_docstore(byte_store)

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
        vector_spec = request.strategy.vector or {}

        if request.target != "index_build":
            raise api_error(400, "invalid_target", "graph_hybrid requires target=index_build", {"target": request.target})

        from rag_lib.retrieval.composition import create_graph_hybrid_retriever

        _, index_row = await self._resolve_index_build(project_id, request.target, request.target_id)
        vector_retriever = self._build_vector_retriever(
            index_row=index_row,
            k=int(vector_spec.get("k", 10)),
            search_type=str(vector_spec.get("search_type", "similarity")),
            score_threshold=vector_spec.get("score_threshold"),
            metadata_filter=vector_spec.get("filter"),
        )
        graph_retriever = _StaticRetriever(documents=graph_docs)
        hybrid = create_graph_hybrid_retriever(
            vector_retriever=vector_retriever,
            graph_retriever=graph_retriever,
            weights=request.strategy.weights or [0.7, 0.3],
        )
        return list(hybrid.invoke(request.query))

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
