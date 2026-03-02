import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_feature
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

    async def create_from_chunk_set(self, chunk_set_id: str, strategy: str, chunker_params: dict) -> ChunkSetVersion:
        parent_chunk_set = await self.session.get(ChunkSetVersion, chunk_set_id)
        if not parent_chunk_set or parent_chunk_set.is_deleted:
            raise api_error(404, "chunk_set_not_found", "Chunk set not found", {"chunk_set_version_id": chunk_set_id})

        parent_chunks = await self._get_chunk_items(chunk_set_id)
        chunk_rows = self._chunk_items(parent_chunks, strategy, chunker_params)

        await self.session.execute(
            update(ChunkSetVersion)
            .where(ChunkSetVersion.project_id == parent_chunk_set.project_id, ChunkSetVersion.is_active.is_(True))
            .values(is_active=False)
        )

        chunk_set = ChunkSetVersion(
            project_id=parent_chunk_set.project_id,
            segment_set_version_id=parent_chunk_set.segment_set_version_id,
            parent_chunk_set_version_id=parent_chunk_set.chunk_set_version_id,
            params_json={"strategy": strategy, "chunker_params": chunker_params},
            input_refs_json={
                "parent_chunk_set_version_id": parent_chunk_set.chunk_set_version_id,
                "segment_set_version_id": parent_chunk_set.segment_set_version_id,
            },
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

    async def _get_chunk_items(self, chunk_set_id: str) -> list[ChunkItem]:
        stmt = (
            select(ChunkItem)
            .where(ChunkItem.chunk_set_version_id == chunk_set_id)
            .order_by(ChunkItem.position.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    def _chunk_items(self, segments: list[SegmentItem], strategy: str, params: dict) -> list[dict]:
        strategy = strategy.lower()

        chunker = self._build_chunker(strategy, params)
        out: list[dict] = []
        segment_output_strategies = {"regex_hierarchy", "markdown_hierarchy", "json", "qa", "csv_table", "html"}

        for seg in segments:
            if strategy in segment_output_strategies and hasattr(chunker, "create_segments"):
                chunks = chunker.create_segments(seg.content, metadata=seg.metadata_json or {})
            else:
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
                            "parent_id": seg.item_id,
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
                keep_separator=bool(params.get("keep_separator", False)),
                is_separator_regex=bool(params.get("is_separator_regex", False)),
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
                language=params.get("language", "auto"),
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

            summarizer = self._build_table_summarizer(params.get("table_summarizer"))
            return MarkdownTableSplitter(
                split_table_rows=bool(params.get("split_table_rows", False)),
                use_first_row_as_header=bool(params.get("use_first_row_as_header", True)),
                max_rows_per_chunk=params.get("max_rows_per_chunk"),
                max_chunk_size=params.get("max_chunk_size"),
                summarizer=summarizer,
                summarize_table=bool(params.get("summarize_table", True)),
                summarize_chunks=bool(params.get("summarize_chunks", False)),
                inject_summaries_into_content=bool(params.get("inject_summaries_into_content", False)),
            )
        if strategy == "regex_hierarchy":
            from rag_lib.chunkers.regex_hierarchy import RegexHierarchySplitter

            patterns = params.get("patterns")
            if not patterns:
                raise api_error(400, "invalid_chunker_params", "regex_hierarchy strategy requires patterns")
            return RegexHierarchySplitter(
                patterns=patterns,
                exclude_patterns=params.get("exclude_patterns"),
                include_parent_content=params.get("include_parent_content", False),
            )
        if strategy == "markdown_hierarchy":
            from rag_lib.chunkers.markdown_hierarchy import MarkdownHierarchySplitter

            return MarkdownHierarchySplitter(
                exclude_code_blocks=params.get("exclude_code_blocks", True),
                include_parent_content=params.get("include_parent_content", False),
            )
        if strategy == "json":
            from rag_lib.chunkers.json import JsonSplitter

            return JsonSplitter(
                schema=params.get("schema", "."),
                schema_dialect=params.get("schema_dialect", "dot_path"),
                ensure_ascii=bool(params.get("ensure_ascii", False)),
                metadata_value_max_len=params.get("metadata_value_max_len", 256),
            )
        if strategy == "qa":
            from rag_lib.chunkers.qa import QASplitter

            return QASplitter()
        if strategy == "csv_table":
            from rag_lib.chunkers.csv_table import CSVTableSplitter

            summarizer = self._build_table_summarizer(params.get("table_summarizer"))
            return CSVTableSplitter(
                max_rows_per_chunk=params.get("max_rows_per_chunk"),
                max_chunk_size=params.get("max_chunk_size"),
                delimiter=params.get("delimiter"),
                use_first_row_as_header=params.get("use_first_row_as_header", True),
                summarizer=summarizer,
                summarize_table=params.get("summarize_table", True),
                summarize_chunks=params.get("summarize_chunks", False),
                inject_summaries_into_content=params.get("inject_summaries_into_content", False),
            )
        if strategy == "html":
            from rag_lib.chunkers.html import HTMLSplitter

            summarizer = self._build_table_summarizer(params.get("table_summarizer"))
            return HTMLSplitter(
                output_format=params.get("output_format", "markdown"),
                split_table_rows=params.get("split_table_rows", False),
                use_first_row_as_header=params.get("use_first_row_as_header", True),
                max_rows_per_chunk=params.get("max_rows_per_chunk"),
                max_chunk_size=params.get("max_chunk_size"),
                summarizer=summarizer,
                summarize_table=params.get("summarize_table", True),
                summarize_chunks=params.get("summarize_chunks", False),
                inject_summaries_into_content=params.get("inject_summaries_into_content", False),
                include_parent_content=params.get("include_parent_content", False),
            )
        if strategy == "semantic":
            from rag_lib.chunkers.semantic import SemanticChunker
            provider = params.get("embedding_provider")
            if provider == "mock":
                from rag_lib.embeddings.mock import MockEmbeddings

                embeddings = MockEmbeddings()
            else:
                from rag_lib.embeddings.factory import create_embeddings_model

                embeddings = create_embeddings_model(
                    provider=provider,
                    model_name=params.get("embedding_model_name"),
                )
            return SemanticChunker(
                embeddings=embeddings,
                threshold=params.get("threshold"),
                threshold_type=params.get("threshold_type", "fixed"),
                language=params.get("language", "auto"),
                percentile_threshold=params.get("percentile_threshold", 90),
                local_percentile_window=params.get("local_percentile_window", 50),
                local_min_samples=params.get("local_min_samples", 20),
                local_fallback=params.get("local_fallback", "global"),
                window_size=params.get("window_size", 1),
                enable_debug=bool(params.get("enable_debug", False)),
            )

        raise api_error(400, "unsupported_chunk_strategy", "Unsupported chunk strategy", {"strategy": strategy})

    def _build_table_summarizer(self, cfg: dict | None):
        if not cfg:
            return None

        kind = str((cfg or {}).get("type", "mock")).lower()
        if kind == "mock":
            from rag_lib.summarizers.table import MockTableSummarizer

            return MockTableSummarizer()

        if kind != "llm":
            raise api_error(400, "invalid_chunker_params", "table_summarizer.type must be mock or llm")

        require_feature(
            settings.feature_enable_llm,
            "llm",
            hint="Set FEATURE_ENABLE_LLM=true and configure provider credentials.",
        )
        from rag_lib.llm.factory import create_llm
        from rag_lib.summarizers.table_llm import LLMTableSummarizer

        try:
            llm = create_llm(
                provider=cfg.get("llm_provider") or settings.llm_provider_default,
                model_name=cfg.get("model") or settings.llm_model_default,
                temperature=settings.llm_temperature_default if cfg.get("temperature") is None else cfg.get("temperature"),
                streaming=False,
            )
        except Exception as exc:
            raise api_error(424, "missing_dependency", "LLM provider initialization failed", {"error": str(exc)}) from exc
        return LLMTableSummarizer(llm=llm)

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
