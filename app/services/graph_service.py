from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.documents import Document as LCDocument
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_feature
from app.core.config import settings
from app.core.errors import api_error
from app.models import GraphBuild, GraphQueryRun, Index, IndexBuild, SegmentItem, SegmentSetVersion
from app.services.vector_store_adapter import create_vector_store_for_retrieval
from app.storage.keys import uri_to_key
from app.storage.object_store import object_store


class GraphService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_build(
        self,
        project_id: str,
        source_type: str,
        source_id: str,
        backend: str | None,
        params: dict[str, Any],
        *,
        status: str = "queued",
    ) -> GraphBuild:
        require_feature(
            settings.feature_enable_graph,
            "graph",
            hint="Set FEATURE_ENABLE_GRAPH=true to enable graph capabilities.",
        )
        await self._validate_source(project_id, source_type, source_id)
        probe_store, resolved_backend = self._create_graph_store(backend)
        close = getattr(probe_store, "close", None)
        if callable(close):
            close()

        row = GraphBuild(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            backend=resolved_backend,
            params_json=params,
            input_refs_json={"source_type": source_type, "source_id": source_id},
            status=status,
            producer_type="rag_lib",
            producer_version=settings.rag_lib_producer_version,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_builds(self, project_id: str) -> list[GraphBuild]:
        stmt = (
            select(GraphBuild)
            .where(GraphBuild.project_id == project_id, GraphBuild.is_deleted.is_(False))
            .order_by(GraphBuild.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_build(self, graph_build_id: str) -> GraphBuild:
        row = await self.session.get(GraphBuild, graph_build_id)
        if not row or row.is_deleted:
            raise api_error(404, "graph_build_not_found", "Graph build not found", {"graph_build_id": graph_build_id})
        return row

    async def run_build(self, graph_build_id: str) -> GraphBuild:
        row = await self.get_build(graph_build_id)
        row.status = "running"
        await self.session.commit()

        segments = await self._load_source_segments(row.project_id, row.source_type, row.source_id)
        if not segments:
            row.status = "failed"
            await self.session.commit()
            raise api_error(400, "empty_source", "Graph source has no items", {"source_type": row.source_type, "source_id": row.source_id})

        store, backend = self._create_graph_store(row.backend)
        params = row.params_json or {}
        communities: dict[int, list[str]] = {}
        summary_segments: list[dict[str, Any]] = []

        try:
            if params.get("extract_entities", True):
                llm = self._get_llm(
                    provider=params.get("llm_provider"),
                    model=params.get("llm_model"),
                    temperature=params.get("llm_temperature"),
                )
                from rag_lib.processors.entity_extractor import EntityExtractor

                extractor = EntityExtractor(llm=llm, store=store)
                extractor.process_segments(segments)

            if params.get("detect_communities", False):
                if backend != "networkx":
                    row.status = "failed"
                    await self.session.commit()
                    raise api_error(
                        400,
                        "invalid_provider_backend",
                        "Community detection currently supports only networkx backend",
                        {"backend": backend},
                    )
                from rag_lib.graph.community import CommunityDetector

                communities = CommunityDetector.detect(store)

            if params.get("summarize_communities", False):
                llm = self._get_llm(
                    provider=params.get("llm_provider"),
                    model=params.get("llm_model"),
                    temperature=params.get("llm_temperature"),
                )
                from rag_lib.processors.community_summarizer import CommunitySummarizer

                summarizer = CommunitySummarizer(llm=llm, store=store)
                summaries = summarizer.summarize(communities)
                for seg in summaries:
                    summary_segments.append(
                        {
                            "content": seg.content,
                            "metadata": seg.metadata,
                        }
                    )

            graph_uri = None
            nodes = None
            edges = None
            if backend == "networkx":
                # Persist graph snapshot for retrieval.
                with tempfile.NamedTemporaryFile(delete=False, suffix=".gml") as tmp:
                    tmp_path = tmp.name
                try:
                    store.save_to_file(tmp_path)
                    graph_bytes = Path(tmp_path).read_bytes()
                finally:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

                graph_key = f"projects/{row.project_id}/graphs/{row.graph_build_id}/graph.gml"
                graph_uri = object_store.put_bytes(graph_key, graph_bytes, content_type="text/plain")
                nodes = int(store.graph.number_of_nodes())
                edges = int(store.graph.number_of_edges())

            manifest = {
                "graph_build_id": row.graph_build_id,
                "project_id": row.project_id,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "backend": backend,
                "graph_uri": graph_uri,
                "communities": communities,
                "community_summaries": summary_segments,
                "node_count": nodes,
                "edge_count": edges,
            }
            key = f"projects/{row.project_id}/graph_builds/{row.graph_build_id}/manifest.json"
            row.artifact_uri = object_store.put_json(key, manifest)

            await self.session.execute(
                update(GraphBuild)
                .where(GraphBuild.project_id == row.project_id, GraphBuild.is_active.is_(True))
                .values(is_active=False)
            )
            row.is_active = True
            row.status = "succeeded"
            await self.session.commit()
            await self.session.refresh(row)
            return row
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()

    async def query_graph(
        self,
        graph_build_id: str,
        project_id: str,
        query: str,
        *,
        mode: str = "hybrid",
        graph_query_config: dict[str, Any] | None = None,
    ) -> list[LCDocument]:
        row = await self.get_build(graph_build_id)
        if row.project_id != project_id:
            raise api_error(404, "graph_build_not_found", "Graph build not found", {"graph_build_id": graph_build_id})
        if row.status != "succeeded":
            raise api_error(409, "graph_build_not_ready", "Graph build is not ready", {"graph_build_id": row.graph_build_id})

        params = row.params_json or {}
        configured_index_build_id = params.get("index_build_id")
        if not configured_index_build_id:
            raise api_error(
                400,
                "graph_index_build_required",
                "Graph retrieval requires graph build params.index_build_id",
                {"graph_build_id": row.graph_build_id},
            )

        store = self._load_store_for_build(row)
        try:
            vector_store = await self._load_vector_store_from_index_build(
                project_id=row.project_id,
                index_build_id=str(configured_index_build_id),
            )
            from rag_lib.retrieval.graph_retriever import GraphQueryConfig
            from rag_lib.retrieval.retrievers import create_graph_retriever

            cfg = GraphQueryConfig(
                mode=mode,
                **(graph_query_config or {}),
            )
            llm = None
            if cfg.enable_keyword_extraction:
                llm = self._get_llm(provider=None, model=None, temperature=None)

            retriever = create_graph_retriever(
                vector_store=vector_store,
                graph_store=store,
                config=cfg,
                llm=llm,
            )
            docs = await retriever.ainvoke(query)
            payload = {
                "items": [
                    {"page_content": d.page_content, "metadata": d.metadata or {}}
                    for d in (docs or [])
                ]
            }
            key = f"projects/{row.project_id}/graph_query_runs/{row.graph_build_id}/{hash(query)}.json"
            uri = object_store.put_json(key, payload)
            run = GraphQueryRun(
                project_id=row.project_id,
                graph_build_id=row.graph_build_id,
                query=query,
                mode=mode,
                config_json=graph_query_config or {},
                result_json=payload,
                artifact_uri=uri,
            )
            self.session.add(run)
            await self.session.commit()
            return list(docs or [])
        except Exception as exc:
            from rag_lib.retrieval.graph_retriever import (
                GraphCapabilityError,
                GraphConfigurationError,
                GraphDataError,
            )

            if isinstance(exc, GraphConfigurationError):
                raise api_error(400, "graph_configuration_error", "Graph query configuration is invalid", {"error": str(exc)}) from exc
            if isinstance(exc, GraphCapabilityError):
                raise api_error(424, "graph_capability_error", "Graph backend capability is unavailable", {"error": str(exc)}) from exc
            if isinstance(exc, GraphDataError):
                raise api_error(400, "graph_data_error", "Graph query input/output data is invalid", {"error": str(exc)}) from exc
            raise api_error(400, "graph_query_failed", "Graph query failed", {"error": str(exc)}) from exc
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()

    async def _load_vector_store_from_index_build(self, project_id: str, index_build_id: str):
        build = await self.session.get(IndexBuild, index_build_id)
        if not build or build.project_id != project_id or build.is_deleted:
            raise api_error(
                404,
                "index_build_not_found",
                "Index build not found",
                {"index_build_id": index_build_id, "project_id": project_id},
            )
        if build.status != "succeeded":
            raise api_error(
                409,
                "index_build_not_ready",
                "Index build is not ready for graph retrieval",
                {"index_build_id": index_build_id, "status": build.status},
            )

        index_row = await self.session.get(Index, build.index_id)
        if not index_row or index_row.is_deleted:
            raise api_error(404, "index_not_found", "Index not found", {"index_id": build.index_id})

        embeddings = self._get_embeddings(
            provider=index_row.config_json.get("embedding_provider", "openai"),
            model_name=index_row.config_json.get("embedding_model_name"),
        )
        return create_vector_store_for_retrieval(index_row=index_row, embeddings=embeddings)

    def _get_embeddings(self, provider: str, model_name: str | None):
        provider_normalized = str(provider).strip().lower() if provider is not None else ""
        provider_normalized = provider_normalized or "openai"

        from rag_lib.embeddings.factory import create_embeddings_model

        try:
            return create_embeddings_model(provider=provider_normalized, model_name=model_name)
        except ValueError as exc:
            raise api_error(
                400,
                "invalid_embedding_provider",
                "Unsupported embedding provider",
                {"provider": provider_normalized, "error": str(exc)},
            ) from exc
        except ImportError as exc:
            raise api_error(
                424,
                "missing_dependency",
                "Embedding provider dependency is not available",
                {"provider": provider_normalized, "error": str(exc)},
            ) from exc
        except Exception as exc:
            raise api_error(
                424,
                "embedding_provider_init_failed",
                "Embedding provider initialization failed",
                {"provider": provider_normalized, "model_name": model_name, "error": str(exc)},
            ) from exc

    def _create_graph_store(self, backend: str | None):
        resolved_backend = (backend or settings.graph_backend_default).strip().lower()
        if resolved_backend not in {"neo4j", "networkx"}:
            raise api_error(
                400,
                "invalid_graph_backend",
                "Unsupported graph backend",
                {"backend": resolved_backend, "allowed": ["neo4j", "networkx"]},
            )

        from rag_lib.graph.store import create_graph_store

        kwargs: dict[str, Any] = {"provider": resolved_backend}
        if resolved_backend == "neo4j":
            kwargs["uri"] = settings.neo4j_uri
            kwargs["auth"] = (settings.neo4j_user, settings.neo4j_password)
            kwargs["database"] = settings.neo4j_database
        try:
            return create_graph_store(**kwargs), resolved_backend
        except ImportError as exc:
            raise api_error(
                424,
                "missing_dependency",
                "Graph backend dependency is not available",
                {"backend": resolved_backend, "error": str(exc)},
            ) from exc
        except ValueError as exc:
            raise api_error(
                400,
                "invalid_graph_backend_config",
                "Graph backend configuration is invalid",
                {"backend": resolved_backend, "error": str(exc)},
            ) from exc
        except Exception as exc:
            raise api_error(
                424,
                "graph_backend_unavailable",
                "Graph backend is unavailable",
                {"backend": resolved_backend, "error": str(exc)},
            ) from exc

    def _load_store_for_build(self, row: GraphBuild):
        store, backend = self._create_graph_store(row.backend)
        if backend != "networkx":
            return store
        if not row.artifact_uri:
            raise api_error(500, "missing_graph_artifact", "Graph artifact is missing", {"graph_build_id": row.graph_build_id})
        key = uri_to_key(row.artifact_uri)
        payload = object_store.get_json(key)
        graph_uri = payload.get("graph_uri")
        if not graph_uri:
            raise api_error(500, "missing_graph_snapshot", "Graph snapshot is missing", {"graph_build_id": row.graph_build_id})
        graph_key = uri_to_key(graph_uri)
        graph_bytes = object_store.get_bytes(graph_key)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gml") as tmp:
            tmp.write(graph_bytes)
            tmp_path = tmp.name
        try:
            store.load_from_file(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return store

    async def _validate_source(self, project_id: str, source_type: str, source_id: str) -> None:
        if source_type != "segment_set":
            raise api_error(400, "invalid_source_type", "source_type must be segment_set", {"source_type": source_type})
        row = await self.session.get(SegmentSetVersion, source_id)
        if not row or row.is_deleted or row.project_id != project_id:
            raise api_error(404, "segment_set_not_found", "Segment set not found", {"segment_set_version_id": source_id})

    async def _load_source_segments(self, project_id: str, source_type: str, source_id: str) -> list:
        await self._validate_source(project_id, source_type, source_id)
        from rag_lib.core.domain import Segment, SegmentType

        stmt = (
            select(SegmentItem)
            .where(SegmentItem.segment_set_version_id == source_id)
            .order_by(SegmentItem.position.asc())
        )
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())

        segments = []
        for row in rows:
            try:
                seg_type = SegmentType(row.type)
            except Exception as exc:
                raise api_error(
                    500,
                    "invalid_segment_type",
                    "Persisted segment item type is invalid",
                    {"item_id": row.item_id, "type": row.type, "allowed": [e.value for e in SegmentType]},
                ) from exc
            segments.append(
                Segment(
                    content=row.content,
                    metadata=row.metadata_json or {},
                    segment_id=row.item_id,
                    parent_id=row.parent_id,
                    level=row.level,
                    path=row.path_json or [],
                    type=seg_type,
                    original_format=row.original_format,
                )
            )
        return segments

    def _get_llm(self, provider: str | None, model: str | None, temperature: float | None):
        require_feature(
            settings.feature_enable_llm,
            "llm",
            hint="Set FEATURE_ENABLE_LLM=true and configure provider credentials.",
        )
        from rag_lib.llm.factory import create_llm

        try:
            return create_llm(
                provider=provider or settings.llm_provider_default,
                model_name=model or settings.llm_model_default,
                temperature=settings.llm_temperature_default if temperature is None else temperature,
                streaming=False,
            )
        except Exception as exc:
            raise api_error(424, "missing_dependency", "LLM provider initialization failed", {"error": str(exc)}) from exc
