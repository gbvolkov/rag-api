from __future__ import annotations

from pathlib import Path
from typing import Any

from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import api_error
from app.models import ChunkItem, ChunkSetVersion, Index, IndexBuild, Job
from app.storage.object_store import object_store
from app.storage.qdrant import get_qdrant_client


class IndexService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_index(self, project_id: str, name: str, provider: str, index_type: str, config: dict, params: dict) -> Index:
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

    async def create_build(self, index_id: str, chunk_set_version_id: str, params: dict, status: str = "queued") -> IndexBuild:
        index_row = await self.get_index(index_id)

        chunk_set = await self.session.get(ChunkSetVersion, chunk_set_version_id)
        if not chunk_set or chunk_set.is_deleted:
            raise api_error(404, "chunk_set_not_found", "Chunk set not found", {"chunk_set_version_id": chunk_set_version_id})

        build = IndexBuild(
            index_id=index_id,
            project_id=index_row.project_id,
            chunk_set_version_id=chunk_set_version_id,
            params_json=params,
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
        if provider not in {"qdrant", "faiss"}:
            build.status = "failed"
            await self.session.commit()
            raise api_error(501, "provider_unsupported", "Only qdrant and faiss providers are currently implemented", {"provider": index_row.provider})

        build.status = "running"
        await self.session.commit()

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

        embeddings = self._get_embeddings(index_row)
        if provider == "qdrant":
            vectors = embeddings.embed_documents([c.content for c in chunks])
            if not vectors:
                build.status = "failed"
                await self.session.commit()
                raise api_error(500, "embedding_failure", "Embedding provider returned no vectors")

            dimension = len(vectors[0])
            collection = index_row.config_json.get(
                "collection_name",
                f"{settings.default_vector_collection_prefix}_{index_row.project_id}_{index_row.index_id}",
            )

            qdrant = get_qdrant_client()
            existing = {c.name for c in qdrant.get_collections().collections}
            if collection not in existing:
                qdrant.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
                )

            points = []
            for chunk, vector in zip(chunks, vectors, strict=True):
                points.append(
                    PointStruct(
                        id=chunk.item_id,
                        vector=vector,
                        payload={
                            "chunk_item_id": chunk.item_id,
                            "content": chunk.content,
                            "metadata": chunk.metadata_json,
                            "chunk_set_version_id": build.chunk_set_version_id,
                        },
                    )
                )
            qdrant.upsert(collection_name=collection, points=points)

            manifest = {
                "provider": "qdrant",
                "collection_name": collection,
                "points": len(points),
                "index_id": index_row.index_id,
                "build_id": build.build_id,
                "chunk_set_version_id": build.chunk_set_version_id,
            }
            index_row.config_json = {**(index_row.config_json or {}), "collection_name": collection}
        else:
            try:
                from langchain_community.vectorstores import FAISS
            except Exception:
                build.status = "failed"
                await self.session.commit()
                raise api_error(
                    424,
                    "missing_dependency",
                    "FAISS provider requires langchain-community/faiss runtime dependencies",
                    {"provider": "faiss"},
                )

            texts = [c.content for c in chunks]
            metadatas = [
                {
                    "chunk_item_id": c.item_id,
                    "chunk_set_version_id": build.chunk_set_version_id,
                    "metadata": c.metadata_json,
                }
                for c in chunks
            ]
            ids = [c.item_id for c in chunks]

            # Build a clean FAISS index from chunk payloads.
            vector_store = FAISS.from_texts(texts=texts, embedding=embeddings, metadatas=metadatas, ids=ids)

            faiss_dir = Path("artifacts") / "faiss" / build.project_id / index_row.index_id / build.build_id
            faiss_dir.mkdir(parents=True, exist_ok=True)
            vector_store.save_local(str(faiss_dir))

            manifest = {
                "provider": "faiss",
                "faiss_local_dir": str(faiss_dir),
                "vectors": len(ids),
                "index_id": index_row.index_id,
                "build_id": build.build_id,
                "chunk_set_version_id": build.chunk_set_version_id,
            }
            index_row.config_json = {**(index_row.config_json or {}), "faiss_local_dir": str(faiss_dir)}

        key = f"projects/{build.project_id}/indexes/{index_row.index_id}/builds/{build.build_id}/manifest.json"
        build.artifact_uri = object_store.put_json(key, manifest)

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

    def _get_embeddings(self, index_row: Index):
        provider = index_row.config_json.get("embedding_provider", "mock")
        model_name = index_row.config_json.get("embedding_model_name")
        if provider == "mock":
            from rag_lib.embeddings.mock import MockEmbeddings

            return MockEmbeddings()

        from rag_lib.embeddings.factory import get_embeddings_model

        return get_embeddings_model(provider=provider, model_name=model_name)

    async def create_job(self, project_id: str, job_type: str, payload: dict) -> Job:
        job = Job(project_id=project_id, job_type=job_type, status="queued", payload_json=payload)
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job
