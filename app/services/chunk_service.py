import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import api_error
from app.models import ChunkItem, ChunkSetVersion, SegmentItem, SegmentSetVersion
from app.storage.object_store import object_store


class ChunkService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_from_segment_set(self, segment_set_id: str, strategy: str, chunker_params: dict) -> ChunkSetVersion:
        segment_set = await self.session.get(SegmentSetVersion, segment_set_id)
        if not segment_set or segment_set.is_deleted:
            raise api_error(404, "segment_set_not_found", "Segment set not found", {"segment_set_version_id": segment_set_id})

        segments = await self._get_segment_items(segment_set_id)
        chunk_rows = self._chunk_items(segments, strategy, chunker_params)

        await self.session.execute(
            update(ChunkSetVersion)
            .where(ChunkSetVersion.project_id == segment_set.project_id, ChunkSetVersion.is_active.is_(True))
            .values(is_active=False)
        )

        chunk_set = ChunkSetVersion(
            project_id=segment_set.project_id,
            segment_set_version_id=segment_set.segment_set_version_id,
            parent_chunk_set_version_id=None,
            params_json={"strategy": strategy, "chunker_params": chunker_params},
            input_refs_json={"segment_set_version_id": segment_set.segment_set_version_id},
            producer_type="rag_lib",
            producer_version=settings.rag_lib_producer_version,
            is_active=True,
        )
        self.session.add(chunk_set)
        await self.session.flush()

        snapshot = []
        for i, row in enumerate(chunk_rows):
            chunk = ChunkItem(
                chunk_set_version_id=chunk_set.chunk_set_version_id,
                item_id=row["item_id"],
                position=i,
                content=row["content"],
                metadata_json=row["metadata"],
                parent_id=row["parent_id"],
                level=row["level"],
                path_json=row["path"],
                type=row["type"],
                original_format=row["original_format"],
            )
            self.session.add(chunk)
            snapshot.append(
                {
                    "item_id": chunk.item_id,
                    "position": chunk.position,
                    "content": chunk.content,
                    "metadata": chunk.metadata_json,
                    "parent_id": chunk.parent_id,
                    "level": chunk.level,
                    "path": chunk.path_json,
                    "type": chunk.type,
                    "original_format": chunk.original_format,
                }
            )

        key = f"projects/{chunk_set.project_id}/chunks/{chunk_set.chunk_set_version_id}/chunks.json"
        chunk_set.artifact_uri = object_store.put_json(key, snapshot)

        await self.session.commit()
        await self.session.refresh(chunk_set)
        return chunk_set

    async def _get_segment_items(self, segment_set_id: str) -> list[SegmentItem]:
        stmt = (
            select(SegmentItem)
            .where(SegmentItem.segment_set_version_id == segment_set_id)
            .order_by(SegmentItem.position.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    def _chunk_items(self, segments: list[SegmentItem], strategy: str, params: dict) -> list[dict]:
        strategy = strategy.lower()

        chunker = self._build_chunker(strategy, params)
        out: list[dict] = []

        for seg in segments:
            chunks = self._split(chunker, strategy, seg.content)
            for idx, chunk in enumerate(chunks):
                if hasattr(chunk, "content"):
                    chunk_content = chunk.content
                    chunk_type = getattr(getattr(chunk, "type", None), "value", None) or str(getattr(chunk, "type", "text"))
                    chunk_fmt = getattr(chunk, "original_format", "text")
                    extra_meta = getattr(chunk, "metadata", {}) or {}
                else:
                    chunk_content = str(chunk)
                    chunk_type = "text"
                    chunk_fmt = "text"
                    extra_meta = {}

                if not chunk_content.strip():
                    continue

                out.append(
                    {
                        "item_id": str(uuid.uuid4()),
                        "content": chunk_content,
                        "metadata": {
                            "source_segment_item_id": seg.item_id,
                            "chunk_index": idx,
                            **extra_meta,
                        },
                        "parent_id": seg.parent_id,
                        "level": seg.level,
                        "path": seg.path_json or [],
                        "type": chunk_type,
                        "original_format": chunk_fmt,
                    }
                )

        return out

    def _build_chunker(self, strategy: str, params: dict):
        if strategy == "recursive":
            from rag_lib.chunkers.recursive import RecursiveCharacterTextSplitter

            return RecursiveCharacterTextSplitter(
                chunk_size=params.get("chunk_size", 4000),
                chunk_overlap=params.get("chunk_overlap", 200),
                separators=params.get("separators"),
            )
        if strategy == "token":
            from rag_lib.chunkers.token import TokenTextSplitter

            return TokenTextSplitter(
                chunk_size=params.get("chunk_size", 4000),
                chunk_overlap=params.get("chunk_overlap", 200),
                model_name=params.get("model_name", "cl100k_base"),
                encoding_name=params.get("encoding_name"),
            )
        if strategy == "sentence":
            from rag_lib.chunkers.sentence import SentenceSplitter

            return SentenceSplitter(
                chunk_size=params.get("chunk_size", 4000),
                chunk_overlap=params.get("chunk_overlap", 200),
                language=params.get("language", "english"),
            )
        if strategy == "regex":
            from rag_lib.chunkers.regex import RegexSplitter

            pattern = params.get("pattern")
            if not pattern:
                raise api_error(400, "invalid_chunker_params", "regex strategy requires pattern")
            return RegexSplitter(
                pattern=pattern,
                chunk_size=params.get("chunk_size", 4000),
                chunk_overlap=params.get("chunk_overlap", 200),
            )
        if strategy == "markdown_table":
            from rag_lib.chunkers.markdown_table import MarkdownTableSplitter

            return MarkdownTableSplitter()
        if strategy == "semantic":
            from rag_lib.chunkers.semantic import SemanticChunker
            from rag_lib.embeddings.factory import get_embeddings_model

            embeddings = get_embeddings_model(
                provider=params.get("embedding_provider"),
                model_name=params.get("embedding_model_name"),
            )
            return SemanticChunker(
                embeddings=embeddings,
                threshold=params.get("threshold"),
                threshold_type=params.get("threshold_type", "fixed"),
                percentile_threshold=params.get("percentile_threshold", 90),
                window_size=params.get("window_size", 1),
            )

        raise api_error(400, "unsupported_chunk_strategy", "Unsupported chunk strategy", {"strategy": strategy})

    def _split(self, chunker, strategy: str, text: str):
        if strategy == "markdown_table":
            return chunker.split_text(text)
        return chunker.split_text(text)

    async def list_chunk_sets(self, project_id: str) -> list[ChunkSetVersion]:
        stmt = (
            select(ChunkSetVersion)
            .where(ChunkSetVersion.project_id == project_id, ChunkSetVersion.is_deleted.is_(False))
            .order_by(ChunkSetVersion.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_chunk_set(self, chunk_set_id: str) -> ChunkSetVersion:
        row = await self.session.get(ChunkSetVersion, chunk_set_id)
        if not row or row.is_deleted:
            raise api_error(404, "chunk_set_not_found", "Chunk set not found", {"chunk_set_version_id": chunk_set_id})
        return row

    async def list_items(self, chunk_set_id: str) -> list[ChunkItem]:
        stmt = (
            select(ChunkItem)
            .where(ChunkItem.chunk_set_version_id == chunk_set_id)
            .order_by(ChunkItem.position.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_items(self, chunk_set_id: str) -> int:
        stmt = select(func.count(ChunkItem.id)).where(ChunkItem.chunk_set_version_id == chunk_set_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def clone_patch_item(self, chunk_set_id: str, item_id: str, patch: dict, params: dict) -> ChunkSetVersion:
        original_set = await self.get_chunk_set(chunk_set_id)
        items = await self.list_items(chunk_set_id)
        target = next((it for it in items if it.item_id == item_id), None)
        if not target:
            raise api_error(404, "chunk_item_not_found", "Chunk item not found", {"item_id": item_id})

        await self.session.execute(
            update(ChunkSetVersion)
            .where(ChunkSetVersion.project_id == original_set.project_id, ChunkSetVersion.is_active.is_(True))
            .values(is_active=False)
        )

        cloned = ChunkSetVersion(
            project_id=original_set.project_id,
            segment_set_version_id=original_set.segment_set_version_id,
            parent_chunk_set_version_id=original_set.chunk_set_version_id,
            params_json={**(original_set.params_json or {}), "clone_patch": params},
            input_refs_json={"parent_chunk_set_version_id": original_set.chunk_set_version_id, "patched_item_id": item_id},
            producer_type=original_set.producer_type,
            producer_version=original_set.producer_version,
            is_active=True,
        )
        self.session.add(cloned)
        await self.session.flush()

        snapshot = []
        for i, src in enumerate(items):
            row = ChunkItem(
                chunk_set_version_id=cloned.chunk_set_version_id,
                item_id=src.item_id,
                position=i,
                content=patch.get("content", src.content) if src.item_id == item_id else src.content,
                metadata_json=patch.get("metadata", src.metadata_json) if src.item_id == item_id else src.metadata_json,
                parent_id=patch.get("parent_id", src.parent_id) if src.item_id == item_id else src.parent_id,
                level=int(patch.get("level", src.level)) if src.item_id == item_id else src.level,
                path_json=patch.get("path", src.path_json) if src.item_id == item_id else src.path_json,
                type=patch.get("type", src.type) if src.item_id == item_id else src.type,
                original_format=patch.get("original_format", src.original_format) if src.item_id == item_id else src.original_format,
            )
            self.session.add(row)
            snapshot.append(
                {
                    "item_id": row.item_id,
                    "position": row.position,
                    "content": row.content,
                    "metadata": row.metadata_json,
                    "parent_id": row.parent_id,
                    "level": row.level,
                    "path": row.path_json,
                    "type": row.type,
                    "original_format": row.original_format,
                }
            )

        key = f"projects/{cloned.project_id}/chunks/{cloned.chunk_set_version_id}/chunks.json"
        cloned.artifact_uri = object_store.put_json(key, snapshot)

        await self.session.commit()
        await self.session.refresh(cloned)
        return cloned
