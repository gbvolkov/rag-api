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
from app.models import ChunkItem, ChunkSetVersion, GraphBuild, SegmentItem, SegmentSetVersion
from app.services.graph_store_factory import create_graph_store
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
        _, resolved_backend = create_graph_store(backend)

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

        store, backend = create_graph_store(row.backend)
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
        query: str,
        *,
        mode: str = "local",
        search_depth: int = 1,
    ) -> list[LCDocument]:
        row = await self.get_build(graph_build_id)
        if row.status != "succeeded":
            raise api_error(409, "graph_build_not_ready", "Graph build is not ready", {"graph_build_id": row.graph_build_id})
        if mode not in {"local", "global"}:
            raise api_error(400, "invalid_graph_mode", "mode must be local or global", {"mode": mode})

        if mode == "global":
            return self._query_global_from_manifest(row, query)

        store = self._load_store_for_build(row)
        try:
            from rag_lib.retrieval.graph_retriever import GraphRetriever

            retriever = GraphRetriever(store=store, mode="local", search_depth=search_depth)
            docs = await retriever.ainvoke(query)
            return list(docs or [])
        finally:
            close = getattr(store, "close", None)
            if callable(close):
                close()

    def _query_global_from_manifest(self, row: GraphBuild, query: str) -> list[LCDocument]:
        if not row.artifact_uri:
            return []
        key = uri_to_key(row.artifact_uri)
        payload = object_store.get_json(key)
        summaries = payload.get("community_summaries", [])
        docs = [
            LCDocument(
                page_content=s.get("content", ""),
                metadata={"source": "graph_community_summary", **(s.get("metadata") or {})},
            )
            for s in summaries
            if s.get("content")
        ]
        if not docs:
            return []
        try:
            from rag_lib.retrieval.retrievers import get_bm25_retriever

            retriever = get_bm25_retriever(docs, k=min(10, len(docs)))
            return list(retriever.invoke(query))
        except Exception:
            q = query.lower()
            return [d for d in docs if q in d.page_content.lower()][:10]

    def _load_store_for_build(self, row: GraphBuild):
        store, backend = create_graph_store(row.backend)
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
        if source_type == "segment_set":
            row = await self.session.get(SegmentSetVersion, source_id)
            if not row or row.is_deleted or row.project_id != project_id:
                raise api_error(404, "segment_set_not_found", "Segment set not found", {"segment_set_version_id": source_id})
            return
        if source_type == "chunk_set":
            row = await self.session.get(ChunkSetVersion, source_id)
            if not row or row.is_deleted or row.project_id != project_id:
                raise api_error(404, "chunk_set_not_found", "Chunk set not found", {"chunk_set_version_id": source_id})
            return
        raise api_error(400, "invalid_source_type", "source_type must be segment_set or chunk_set", {"source_type": source_type})

    async def _load_source_segments(self, project_id: str, source_type: str, source_id: str) -> list:
        await self._validate_source(project_id, source_type, source_id)
        from rag_lib.core.domain import Segment, SegmentType

        if source_type == "segment_set":
            stmt = (
                select(SegmentItem)
                .where(SegmentItem.segment_set_version_id == source_id)
                .order_by(SegmentItem.position.asc())
            )
            result = await self.session.execute(stmt)
            rows = list(result.scalars().all())
        else:
            stmt = (
                select(ChunkItem)
                .where(ChunkItem.chunk_set_version_id == source_id)
                .order_by(ChunkItem.position.asc())
            )
            result = await self.session.execute(stmt)
            rows = list(result.scalars().all())

        segments = []
        for row in rows:
            try:
                seg_type = SegmentType(row.type)
            except Exception:
                seg_type = SegmentType.TEXT
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
        from rag_lib.llm.factory import get_llm

        try:
            return get_llm(
                provider=provider or settings.llm_provider_default,
                model=model or settings.llm_model_default,
                temperature=settings.llm_temperature_default if temperature is None else temperature,
                streaming=False,
            )
        except Exception as exc:
            raise api_error(424, "missing_dependency", "LLM provider initialization failed", {"error": str(exc)}) from exc
