from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_choice
from app.core.config import settings
from app.core.errors import api_error
from app.models import ChunkItem, ChunkSetVersion, Index, IndexBuild, Job, SegmentItem
from app.services.vector_store_adapter import create_vector_store_for_build, vector_store_manifest
from app.storage.object_store import object_store


class IndexService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_index(self, project_id: str, name: str, provider: str, index_type: str, config: dict, params: dict) -> Index:
        require_choice(
            provider.lower(),
            {"qdrant", "faiss", "chroma", "postgres"},
            code="invalid_index_provider",
            message="Unsupported index provider",
            field="provider",
        )
        row = Index(
            project_id=project_id,
            name=name,
            provider=provider,
            index_type=index_type,
            config_json=config,
            params_json=params,
            status="created",
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_indexes(self, project_id: str) -> list[Index]:
        stmt = (
            select(Index)
            .where(Index.project_id == project_id, Index.is_deleted.is_(False))
            .order_by(Index.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_index(self, index_id: str) -> Index:
        row = await self.session.get(Index, index_id)
        if not row or row.is_deleted:
            raise api_error(404, "index_not_found", "Index not found", {"index_id": index_id})
        return row

    async def create_build(
        self,
        index_id: str,
        chunk_set_version_id: str,
        params: dict,
        doc_store: dict[str, Any] | None = None,
        status: str = "queued",
    ) -> IndexBuild:
        index_row = await self.get_index(index_id)

        chunk_set = await self.session.get(ChunkSetVersion, chunk_set_version_id)
        if not chunk_set or chunk_set.is_deleted:
            raise api_error(404, "chunk_set_not_found", "Chunk set not found", {"chunk_set_version_id": chunk_set_version_id})

        payload_params = dict(params or {})
        if doc_store is not None:
            payload_params["doc_store"] = doc_store

        build = IndexBuild(
            index_id=index_id,
            project_id=index_row.project_id,
            chunk_set_version_id=chunk_set_version_id,
            params_json=payload_params,
            input_refs_json={"chunk_set_version_id": chunk_set_version_id},
            status=status,
            producer_type="rag_lib",
            producer_version=settings.rag_lib_producer_version,
        )
        self.session.add(build)
        await self.session.commit()
        await self.session.refresh(build)
        return build

    async def list_builds(self, index_id: str) -> list[IndexBuild]:
        stmt = (
            select(IndexBuild)
            .where(IndexBuild.index_id == index_id, IndexBuild.is_deleted.is_(False))
            .order_by(IndexBuild.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_build(self, build_id: str) -> IndexBuild:
        row = await self.session.get(IndexBuild, build_id)
        if not row or row.is_deleted:
            raise api_error(404, "index_build_not_found", "Index build not found", {"build_id": build_id})
        return row

    async def run_build(self, build_id: str) -> IndexBuild:
        build = await self.get_build(build_id)
        index_row = await self.get_index(build.index_id)

        provider = index_row.provider.lower()
        if provider not in {"qdrant", "faiss", "chroma", "postgres"}:
            build.status = "failed"
            await self.session.commit()
            raise api_error(501, "provider_unsupported", "Provider is not implemented", {"provider": index_row.provider})

        build.status = "running"
        await self.session.commit()

        chunk_set_row = await self.session.get(ChunkSetVersion, build.chunk_set_version_id)
        if not chunk_set_row or chunk_set_row.is_deleted:
            build.status = "failed"
            await self.session.commit()
            raise api_error(404, "chunk_set_not_found", "Chunk set not found", {"chunk_set_version_id": build.chunk_set_version_id})

        chunk_stmt = (
            select(ChunkItem)
            .where(ChunkItem.chunk_set_version_id == build.chunk_set_version_id)
            .order_by(ChunkItem.position.asc())
        )
        chunks_res = await self.session.execute(chunk_stmt)
        chunks = list(chunks_res.scalars().all())

        if not chunks:
            build.status = "failed"
            await self.session.commit()
            raise api_error(400, "empty_chunk_set", "Chunk set has no items", {"chunk_set_version_id": build.chunk_set_version_id})

        cfg = dict(index_row.config_json or {})
        if provider in {"qdrant", "chroma", "postgres"}:
            cfg.setdefault(
                "collection_name",
                f"{settings.default_vector_collection_prefix}_{index_row.project_id}_{index_row.index_id}",
            )
        if provider == "postgres":
            connection = cfg.get("connection") or settings.vector_postgres_connection
            if not connection:
                build.status = "failed"
                await self.session.commit()
                raise api_error(400, "missing_index_config", "Postgres provider requires connection string", {"provider": "postgres"})
            cfg["connection"] = connection
        index_row.config_json = cfg

        embeddings = self._get_embeddings(index_row)

        doc_store_config = (build.params_json or {}).get("doc_store")
        doc_store_manifest: dict[str, Any] | None = None

        try:
            if doc_store_config is not None:
                doc_store_manifest = await self._build_doc_store_manifest(
                    build=build,
                    chunk_set_row=chunk_set_row,
                    chunks=chunks,
                    config=doc_store_config,
                )
            vector_store = create_vector_store_for_build(index_row=index_row, embeddings=embeddings)
            from rag_lib.core.indexer import Indexer

            indexer = Indexer(vector_store=vector_store, embeddings=embeddings)
            indexer.index(
                segments=self._chunks_to_segments(chunks),
                parent_segments=None,
                batch_size=int((build.params_json or {}).get("batch_size", 100)),
            )

            if provider == "faiss":
                faiss_dir = Path("artifacts") / "faiss" / build.project_id / index_row.index_id / build.build_id
                faiss_dir.mkdir(parents=True, exist_ok=True)
                save_local = getattr(vector_store, "save_local", None)
                if not callable(save_local):
                    raise api_error(
                        424,
                        "vector_store_unavailable",
                        "FAISS vector store cannot be persisted in current runtime",
                        {"index_id": index_row.index_id},
                    )
                save_local(str(faiss_dir))
                cfg = dict(index_row.config_json or {})
                cfg["faiss_local_dir"] = str(faiss_dir)
                index_row.config_json = cfg

            manifest = vector_store_manifest(index_row=index_row, build_id=build.build_id, count=len(chunks))
            manifest["chunk_set_version_id"] = build.chunk_set_version_id
            if doc_store_manifest is not None:
                manifest["doc_store"] = doc_store_manifest
        except Exception:
            build.status = "failed"
            await self.session.commit()
            raise

        key = f"projects/{build.project_id}/indexes/{index_row.index_id}/builds/{build.build_id}/manifest.json"
        build.artifact_uri = object_store.put_json(key, manifest)
        input_refs = dict(build.input_refs_json or {})
        if doc_store_manifest is not None:
            input_refs["doc_store"] = doc_store_manifest
        else:
            input_refs.pop("doc_store", None)
        build.input_refs_json = input_refs

        await self.session.execute(
            update(IndexBuild)
            .where(IndexBuild.index_id == index_row.index_id, IndexBuild.is_active.is_(True))
            .values(is_active=False)
        )
        build.is_active = True
        build.status = "succeeded"

        index_row.status = "ready"

        await self.session.commit()
        await self.session.refresh(build)
        return build

    async def _build_doc_store_manifest(
        self,
        *,
        build: IndexBuild,
        chunk_set_row: ChunkSetVersion,
        chunks: list[ChunkItem],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        source = str(config.get("source", "auto")).lower()
        if source not in {"auto", "segment_set", "parent_chunk_set"}:
            raise api_error(
                400,
                "invalid_doc_store_source",
                "doc_store.source must be one of auto, segment_set, parent_chunk_set",
                {"source": source},
            )

        id_key_raw = config.get("id_key", "parent_id")
        id_key = str(id_key_raw).strip() if id_key_raw is not None else "parent_id"
        if not id_key:
            raise api_error(400, "invalid_doc_store_id_key", "doc_store.id_key must be a non-empty string")

        if source == "auto":
            source = "parent_chunk_set" if chunk_set_row.parent_chunk_set_version_id else "segment_set"

        if source == "segment_set":
            source_id = chunk_set_row.segment_set_version_id
        else:
            source_id = chunk_set_row.parent_chunk_set_version_id
            if not source_id:
                raise api_error(
                    400,
                    "doc_store_source_unavailable",
                    "Requested doc_store source parent_chunk_set is unavailable for chunk set",
                    {"chunk_set_version_id": chunk_set_row.chunk_set_version_id},
                )

        parent_ids: list[str] = []
        seen: set[str] = set()
        missing_parent_key_chunk_ids: list[str] = []
        for chunk in chunks:
            metadata = chunk.metadata_json or {}
            parent_id = metadata.get(id_key)
            if parent_id is None:
                missing_parent_key_chunk_ids.append(chunk.item_id)
                continue
            parent_id_str = str(parent_id)
            if parent_id_str in seen:
                continue
            seen.add(parent_id_str)
            parent_ids.append(parent_id_str)

        if missing_parent_key_chunk_ids:
            raise api_error(
                400,
                "doc_store_parent_key_missing",
                "Chunk metadata is missing configured doc_store id_key",
                {
                    "id_key": id_key,
                    "missing_parent_key_chunk_ids": missing_parent_key_chunk_ids[:50],
                    "missing_parent_key_count": len(missing_parent_key_chunk_ids),
                },
            )

        if not parent_ids:
            raise api_error(
                400,
                "doc_store_empty_parent_ids",
                "Configured doc_store id_key produced no parent ids",
                {"id_key": id_key},
            )

        parent_docs_by_id: dict[str, dict[str, Any]] = {}
        if source == "segment_set":
            parent_stmt = select(SegmentItem).where(
                SegmentItem.segment_set_version_id == source_id,
                SegmentItem.item_id.in_(parent_ids),
            )
            parent_res = await self.session.execute(parent_stmt)
            parent_rows = list(parent_res.scalars().all())
            for row in parent_rows:
                parent_docs_by_id[row.item_id] = {
                    "id": row.item_id,
                    "page_content": row.content,
                    "metadata": {
                        **self._sanitize_metadata(row.metadata_json or {}),
                        "item_id": row.item_id,
                        id_key: row.item_id,
                        "segment_set_version_id": row.segment_set_version_id,
                    },
                }
        else:
            parent_stmt = select(ChunkItem).where(
                ChunkItem.chunk_set_version_id == source_id,
                ChunkItem.item_id.in_(parent_ids),
            )
            parent_res = await self.session.execute(parent_stmt)
            parent_rows = list(parent_res.scalars().all())
            for row in parent_rows:
                parent_docs_by_id[row.item_id] = {
                    "id": row.item_id,
                    "page_content": row.content,
                    "metadata": {
                        **self._sanitize_metadata(row.metadata_json or {}),
                        "item_id": row.item_id,
                        id_key: row.item_id,
                        "chunk_set_version_id": row.chunk_set_version_id,
                    },
                }

        missing_parent_ids = [pid for pid in parent_ids if pid not in parent_docs_by_id]
        if missing_parent_ids:
            raise api_error(
                400,
                "doc_store_parent_not_found",
                "Parent ids referenced by chunks were not found in configured doc_store source",
                {
                    "source": source,
                    "source_id": source_id,
                    "missing_parent_ids": missing_parent_ids[:50],
                    "missing_parent_count": len(missing_parent_ids),
                },
            )

        items = [parent_docs_by_id[parent_id] for parent_id in parent_ids]
        doc_store_payload = {
            "version": 1,
            "index_id": build.index_id,
            "build_id": build.build_id,
            "source": {"type": source, "id": source_id},
            "id_key": id_key,
            "items": items,
        }
        key = f"projects/{build.project_id}/indexes/{build.index_id}/builds/{build.build_id}/doc_store.json"
        artifact_uri = object_store.put_json(key, doc_store_payload)

        return {
            "source": source,
            "source_id": source_id,
            "id_key": id_key,
            "artifact_uri": artifact_uri,
            "total_items": len(items),
        }

    def _sanitize_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in (metadata or {}).items():
            if not isinstance(key, str):
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                out[key] = value
            else:
                out[key] = str(value)
        return out

    def _chunks_to_segments(self, chunks: list[ChunkItem]):
        from rag_lib.core.domain import Segment, SegmentType

        segments = []
        for chunk in chunks:
            try:
                seg_type = SegmentType(chunk.type)
            except Exception as exc:
                raise api_error(
                    500,
                    "invalid_segment_type",
                    "Persisted chunk item type is invalid",
                    {"item_id": chunk.item_id, "type": chunk.type, "allowed": [e.value for e in SegmentType]},
                ) from exc

            segments.append(
                Segment(
                    content=chunk.content,
                    metadata={
                        "chunk_item_id": chunk.item_id,
                        "chunk_set_version_id": chunk.chunk_set_version_id,
                        **self._sanitize_metadata(chunk.metadata_json or {}),
                    },
                    segment_id=chunk.item_id,
                    parent_id=chunk.parent_id,
                    level=chunk.level,
                    path=chunk.path_json or [],
                    type=seg_type,
                    original_format=chunk.original_format,
                )
            )
        return segments

    def _get_embeddings(self, index_row: Index):
        provider = index_row.config_json.get("embedding_provider", "mock")
        model_name = index_row.config_json.get("embedding_model_name")
        if provider == "mock":
            from rag_lib.embeddings.mock import MockEmbeddings

            return MockEmbeddings()

        from rag_lib.embeddings.factory import create_embeddings_model

        return create_embeddings_model(provider=provider, model_name=model_name)

    async def create_job(self, project_id: str, job_type: str, payload: dict) -> Job:
        job = Job(project_id=project_id, job_type=job_type, status="queued", payload_json=payload)
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job
