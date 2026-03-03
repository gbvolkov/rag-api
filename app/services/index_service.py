from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_choice
from app.core.config import settings
from app.core.errors import api_error
from app.models import Index, IndexBuild, Job, SegmentItem, SegmentSetVersion
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
        source_set_id: str,
        parent_set_id: str | None,
        id_key: str | None,
        params: dict,
        doc_store: dict[str, Any] | None = None,
        status: str = "queued",
    ) -> IndexBuild:
        index_row = await self.get_index(index_id)

        source_set = await self.session.get(SegmentSetVersion, source_set_id)
        if not source_set or source_set.is_deleted or source_set.project_id != index_row.project_id:
            raise api_error(404, "segment_set_not_found", "Source segment set not found", {"source_set_id": source_set_id})

        if parent_set_id:
            parent_set = await self.session.get(SegmentSetVersion, parent_set_id)
            if not parent_set or parent_set.is_deleted or parent_set.project_id != index_row.project_id:
                raise api_error(404, "segment_set_not_found", "Parent segment set not found", {"parent_set_id": parent_set_id})

        if doc_store is not None:
            if not parent_set_id:
                raise api_error(
                    400,
                    "invalid_index_build_config",
                    "parent_set_id is required when doc_store is configured",
                )
            if not isinstance(id_key, str) or not id_key.strip():
                raise api_error(
                    400,
                    "invalid_index_build_config",
                    "id_key is required when doc_store is configured",
                )
            id_key = id_key.strip()

        payload_params = dict(params or {})
        if doc_store is not None:
            payload_params["doc_store"] = doc_store

        input_refs = {"source_set_id": source_set_id}
        if parent_set_id:
            input_refs["parent_set_id"] = parent_set_id
        if id_key:
            input_refs["id_key"] = id_key

        build = IndexBuild(
            index_id=index_id,
            project_id=index_row.project_id,
            source_set_id=source_set_id,
            parent_set_id=parent_set_id,
            params_json=payload_params,
            input_refs_json=input_refs,
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

        source_set = await self.session.get(SegmentSetVersion, build.source_set_id)
        if not source_set or source_set.is_deleted:
            build.status = "failed"
            await self.session.commit()
            raise api_error(404, "segment_set_not_found", "Source segment set not found", {"source_set_id": build.source_set_id})

        source_stmt = (
            select(SegmentItem)
            .where(SegmentItem.segment_set_version_id == build.source_set_id)
            .order_by(SegmentItem.position.asc())
        )
        source_res = await self.session.execute(source_stmt)
        source_items = list(source_res.scalars().all())

        if not source_items:
            build.status = "failed"
            await self.session.commit()
            raise api_error(400, "empty_segment_set", "Source segment set has no items", {"source_set_id": build.source_set_id})

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
        parent_segments = None
        indexer_doc_store = None

        try:
            if doc_store_config is not None:
                id_key_raw = (build.input_refs_json or {}).get("id_key")
                if not isinstance(id_key_raw, str) or not id_key_raw.strip():
                    raise api_error(500, "invalid_index_build", "Index build id_key is missing", {"build_id": build.build_id})
                if not build.parent_set_id:
                    raise api_error(500, "invalid_index_build", "Index build parent_set_id is missing", {"build_id": build.build_id})
                doc_store_manifest, parent_segments, indexer_doc_store = await self._build_doc_store_manifest(
                    build=build,
                    source_items=source_items,
                    parent_set_id=build.parent_set_id,
                    id_key=id_key_raw.strip(),
                    config=doc_store_config,
                )
            vector_store = create_vector_store_for_build(index_row=index_row, embeddings=embeddings)
            from rag_lib.core.indexer import Indexer

            indexer = Indexer(
                vector_store=vector_store,
                embeddings=embeddings,
                doc_store=indexer_doc_store,
            )
            indexer.index(
                segments=self._segment_items_to_segments(source_items),
                parent_segments=parent_segments,
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

            manifest = vector_store_manifest(index_row=index_row, build_id=build.build_id, count=len(source_items))
            manifest["source_set_id"] = build.source_set_id
            if build.parent_set_id:
                manifest["parent_set_id"] = build.parent_set_id
            if (build.input_refs_json or {}).get("id_key"):
                manifest["id_key"] = (build.input_refs_json or {}).get("id_key")
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
        source_items: list[SegmentItem],
        parent_set_id: str,
        id_key: str,
        config: dict[str, Any],
    ) -> tuple[dict[str, Any], list[Any], Any]:
        parent_ids: list[str] = []
        seen: set[str] = set()
        missing_parent_key_item_ids: list[str] = []
        for item in source_items:
            metadata = item.metadata_json or {}
            parent_id = metadata.get(id_key)
            if parent_id is None:
                missing_parent_key_item_ids.append(item.item_id)
                continue
            parent_id_str = str(parent_id)
            if parent_id_str in seen:
                continue
            seen.add(parent_id_str)
            parent_ids.append(parent_id_str)

        if missing_parent_key_item_ids:
            raise api_error(
                400,
                "doc_store_parent_key_missing",
                "Source segment metadata is missing configured id_key",
                {
                    "id_key": id_key,
                    "missing_parent_key_item_ids": missing_parent_key_item_ids[:50],
                    "missing_parent_key_count": len(missing_parent_key_item_ids),
                },
            )

        if not parent_ids:
            raise api_error(
                400,
                "doc_store_empty_parent_ids",
                "Configured id_key produced no parent ids",
                {"id_key": id_key},
            )

        parent_stmt = select(SegmentItem).where(
            SegmentItem.segment_set_version_id == parent_set_id,
            SegmentItem.item_id.in_(parent_ids),
        )
        parent_res = await self.session.execute(parent_stmt)
        parent_rows = list(parent_res.scalars().all())
        parent_segments_by_id = {row.item_id: self._segment_item_to_segment(row) for row in parent_rows}

        missing_parent_ids = [pid for pid in parent_ids if pid not in parent_segments_by_id]
        if missing_parent_ids:
            raise api_error(
                400,
                "doc_store_parent_not_found",
                "Parent ids referenced by source segments were not found in parent_set_id",
                {
                    "parent_set_id": parent_set_id,
                    "missing_parent_ids": missing_parent_ids[:50],
                    "missing_parent_count": len(missing_parent_ids),
                },
            )

        ordered_parent_segments = [parent_segments_by_id[parent_id] for parent_id in parent_ids]
        doc_store, artifact_uri, backend_meta = self._create_persistent_doc_store(build=build, config=config)

        return (
            {
                "source_set_id": parent_set_id,
                "id_key": id_key,
                "artifact_uri": artifact_uri,
                "total_items": len(ordered_parent_segments),
                **backend_meta,
            },
            ordered_parent_segments,
            doc_store,
        )

    def _segment_items_to_segments(self, rows: list[SegmentItem]):
        return [self._segment_item_to_segment(row) for row in rows]

    def _segment_item_to_segment(self, row: SegmentItem):
        from rag_lib.core.domain import Segment

        return Segment(
            content=row.content,
            metadata={
                "item_id": row.item_id,
                "segment_set_version_id": row.segment_set_version_id,
                **dict(row.metadata_json or {}),
            },
            segment_id=row.item_id,
            parent_id=row.parent_id,
            level=row.level,
            path=row.path_json or [],
            type=self._parse_segment_type(row.type, row.item_id),
            original_format=row.original_format,
        )

    def _parse_segment_type(self, raw_type: str, item_id: str):
        from rag_lib.core.domain import SegmentType

        try:
            return SegmentType(raw_type)
        except Exception as exc:
            raise api_error(
                500,
                "invalid_segment_type",
                "Persisted segment item type is invalid",
                {"item_id": item_id, "type": raw_type, "allowed": [e.value for e in SegmentType]},
            ) from exc

    def _create_persistent_doc_store(self, *, build: IndexBuild, config: dict[str, Any]):
        backend_raw = config.get("backend")
        if not isinstance(backend_raw, str) or not backend_raw.strip():
            raise api_error(
                400,
                "invalid_doc_store_backend",
                "doc_store.backend must be provided and be one of local_file, redis",
            )
        backend = backend_raw.strip().lower()
        if backend not in {"local_file", "redis"}:
            raise api_error(
                400,
                "invalid_doc_store_backend",
                "doc_store.backend must be one of local_file, redis",
                {"backend": backend_raw},
            )

        if backend == "local_file":
            from langchain_classic.storage import LocalFileStore, create_kv_docstore

            store_root = (
                Path(settings.local_object_store_path)
                / "projects"
                / build.project_id
                / "indexes"
                / build.index_id
                / "builds"
                / build.build_id
                / "doc_store"
            )
            store_root.mkdir(parents=True, exist_ok=True)
            byte_store = LocalFileStore(store_root)
            return create_kv_docstore(byte_store), str(store_root), {"backend": "local_file"}

        redis_url_raw = config.get("redis_url")
        if not isinstance(redis_url_raw, str) or not redis_url_raw.strip():
            raise api_error(
                400,
                "invalid_doc_store_redis_url",
                "doc_store.redis_url is required when backend=redis",
                {"redis_url": redis_url_raw},
            )
        redis_url = redis_url_raw.strip()

        namespace_raw = config.get("redis_namespace")
        if not isinstance(namespace_raw, str) or not namespace_raw.strip():
            raise api_error(
                400,
                "invalid_doc_store_redis_namespace",
                "doc_store.redis_namespace is required when backend=redis",
                {"redis_namespace": namespace_raw},
            )
        namespace = namespace_raw.strip()

        ttl_raw = config.get("redis_ttl")
        try:
            redis_ttl = int(ttl_raw)
        except (TypeError, ValueError) as exc:
            raise api_error(
                400,
                "invalid_doc_store_redis_ttl",
                "doc_store.redis_ttl must be a positive integer when backend=redis",
                {"redis_ttl": ttl_raw},
            ) from exc
        if redis_ttl <= 0:
            raise api_error(
                400,
                "invalid_doc_store_redis_ttl",
                "doc_store.redis_ttl must be a positive integer when backend=redis",
                {"redis_ttl": ttl_raw},
            )

        from langchain_classic.storage import RedisStore, create_kv_docstore

        byte_store = RedisStore(redis_url=redis_url, namespace=namespace, ttl=redis_ttl)
        return create_kv_docstore(byte_store), redis_url, {
            "backend": "redis",
            "redis_namespace": namespace,
            "redis_ttl": redis_ttl,
        }

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
