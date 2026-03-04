import uuid
from typing import Any, Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_feature
from app.core.config import settings
from app.core.errors import api_error
from app.models import DocumentItem, DocumentSetVersion, SegmentItem, SegmentSetVersion
from app.storage.object_store import object_store


def _segment_to_row(seg: object, position: int) -> dict[str, Any]:
    item_id = getattr(seg, "segment_id", None) or str(uuid.uuid4())
    metadata = getattr(seg, "metadata", {}) or {}
    path = getattr(seg, "path", []) or []
    seg_type = getattr(getattr(seg, "type", None), "value", None) or str(getattr(seg, "type", "text"))
    return {
        "item_id": str(item_id),
        "position": position,
        "content": getattr(seg, "content", ""),
        "metadata_json": metadata,
        "parent_id": getattr(seg, "parent_id", None),
        "level": int(getattr(seg, "level", 0) or 0),
        "path_json": path,
        "type": seg_type,
        "original_format": getattr(seg, "original_format", "text") or "text",
    }


class SegmentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_from_document_set(
        self,
        *,
        document_set_id: str,
        split_strategy: str,
        splitter_params: dict[str, Any] | None,
        params: dict[str, Any] | None = None,
    ) -> SegmentSetVersion:
        document_set = await self.get_document_set(document_set_id)
        document_items = await self.list_document_items(document_set_id)
        if not document_items:
            raise api_error(
                400,
                "empty_document_set",
                "Document set has no items",
                {"document_set_version_id": document_set_id},
            )

        from rag_lib.core.domain import Segment

        source_segments = [
            Segment(
                segment_id=row.item_id,
                content=row.content,
                metadata=dict(row.metadata_json or {}),
                parent_id=None,
                level=0,
                path=[],
                type="text",
                original_format=row.original_format,
            )
            for row in document_items
        ]

        split_segments = self._apply_split_strategy(
            source_segments,
            split_strategy=split_strategy,
            splitter_params=splitter_params,
        )

        return await self.create_derived_from_segments(
            project_id=document_set.project_id,
            document_version_id=document_set.document_version_id,
            parent_segment_set_version_id=None,
            segments=split_segments,
            params={
                "split_strategy": split_strategy,
                "splitter_params": splitter_params or {},
                "params": params or {},
            },
            input_refs={
                "document_set_version_id": document_set.document_set_version_id,
                "operation": "create_from_document_set",
            },
        )

    async def create_derived_from_segments(
        self,
        *,
        project_id: str,
        document_version_id: str | None,
        parent_segment_set_version_id: str | None,
        segments: list[object],
        params: dict[str, Any],
        input_refs: dict[str, Any],
    ) -> SegmentSetVersion:
        if document_version_id:
            await self.session.execute(
                update(SegmentSetVersion)
                .where(SegmentSetVersion.document_version_id == document_version_id, SegmentSetVersion.is_active.is_(True))
                .values(is_active=False)
            )

        segment_set = SegmentSetVersion(
            project_id=project_id,
            document_version_id=document_version_id,
            parent_segment_set_version_id=parent_segment_set_version_id,
            params_json=params,
            input_refs_json=input_refs,
            producer_type="rag_lib",
            producer_version=settings.rag_lib_producer_version,
            is_active=True,
        )
        self.session.add(segment_set)
        await self.session.flush()

        rows: list[SegmentItem] = []
        snapshot: list[dict[str, Any]] = []
        for i, seg in enumerate(segments):
            mapped = _segment_to_row(seg, i)
            row = SegmentItem(segment_set_version_id=segment_set.segment_set_version_id, **mapped)
            rows.append(row)
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

        self.session.add_all(rows)

        key = f"projects/{project_id}/segments/{segment_set.segment_set_version_id}/segments.json"
        artifact_uri = object_store.put_json(key, snapshot)
        segment_set.artifact_uri = artifact_uri

        mirror_key = f"projects/{project_id}/metadata_mirror/segment_set/{segment_set.segment_set_version_id}.json"
        object_store.put_json(
            mirror_key,
            {
                "segment_set_version_id": segment_set.segment_set_version_id,
                "project_id": segment_set.project_id,
                "document_version_id": segment_set.document_version_id,
                "params": segment_set.params_json,
                "input_refs": segment_set.input_refs_json,
                "artifact_uri": segment_set.artifact_uri,
            },
        )

        await self.session.commit()
        await self.session.refresh(segment_set)
        return segment_set

    async def split_from_segment_set(
        self,
        segment_set_id: str,
        strategy: str,
        splitter_params: dict[str, Any] | None,
        params: dict[str, Any] | None = None,
    ) -> SegmentSetVersion:
        source_set = await self.get_segment_set(segment_set_id)
        source_items = await self.list_items(segment_set_id)
        if not source_items:
            raise api_error(
                400,
                "empty_segment_set",
                "Segment set has no items",
                {"segment_set_version_id": segment_set_id},
            )

        from rag_lib.core.domain import Segment

        source_segments = [
            Segment(
                segment_id=row.item_id,
                content=row.content,
                metadata=dict(row.metadata_json or {}),
                parent_id=row.parent_id,
                level=row.level,
                path=list(row.path_json or []),
                type=row.type,
                original_format=row.original_format,
            )
            for row in source_items
        ]

        split_segments = self._apply_split_strategy(
            source_segments,
            split_strategy=strategy,
            splitter_params=splitter_params,
        )

        return await self.create_derived_from_segments(
            project_id=source_set.project_id,
            document_version_id=source_set.document_version_id,
            parent_segment_set_version_id=source_set.segment_set_version_id,
            segments=split_segments,
            params={
                "split_strategy": strategy,
                "splitter_params": splitter_params or {},
                "params": params or {},
            },
            input_refs={
                "parent_segment_set_version_id": source_set.segment_set_version_id,
                "operation": "split",
            },
        )

    def _apply_split_strategy(
        self,
        segments: list[object],
        *,
        split_strategy: str | None,
        splitter_params: dict[str, Any] | None,
    ) -> list[object]:
        if not split_strategy:
            return segments

        strategy = split_strategy.lower()
        if strategy == "identity":
            return segments

        from rag_lib.core.domain import Segment

        params = splitter_params or {}
        splitter = self._build_splitter(strategy, params)
        segment_output_strategies = {"regex_hierarchy", "markdown_hierarchy", "json", "qa", "csv_table", "html"}

        out: list[Segment] = []
        for source in segments:
            source_content = str(getattr(source, "content", "") or "")
            if not source_content.strip():
                continue

            source_metadata = dict(getattr(source, "metadata", {}) or {})
            source_segment_id = str(getattr(source, "segment_id", None) or uuid.uuid4())

            if strategy in segment_output_strategies and hasattr(splitter, "create_segments"):
                split_items = splitter.create_segments(source_content, metadata=source_metadata)
            else:
                split_items = splitter.split_text(source_content)

            for split_index, split_item in enumerate(split_items):
                if hasattr(split_item, "content"):
                    split_content = str(getattr(split_item, "content", "") or "")
                    if not split_content.strip():
                        continue

                    split_metadata = {
                        **source_metadata,
                        **(getattr(split_item, "metadata", {}) or {}),
                    }
                    split_metadata.setdefault("source_segment_item_id", source_segment_id)
                    out.append(
                        Segment(
                            segment_id=str(getattr(split_item, "segment_id", None) or uuid.uuid4()),
                            content=split_content,
                            metadata=split_metadata,
                            parent_id=getattr(split_item, "parent_id", None),
                            level=int(getattr(split_item, "level", 0) or 0),
                            path=list(getattr(split_item, "path", []) or []),
                            type=getattr(split_item, "type", "text"),
                            original_format=getattr(split_item, "original_format", "text") or "text",
                        )
                    )
                    continue

                split_content = str(split_item or "")
                if not split_content.strip():
                    continue
                out.append(
                    Segment(
                        segment_id=str(uuid.uuid4()),
                        content=split_content,
                        metadata={
                            **source_metadata,
                            "source_segment_item_id": source_segment_id,
                            "split_chunk_index": split_index,
                        },
                        parent_id=source_segment_id,
                    )
                )

        if not out:
            raise api_error(
                400,
                "empty_segments_after_split",
                "Split strategy produced no segments",
                {"split_strategy": strategy, "splitter_params": params},
            )
        return out

    def _build_splitter(self, strategy: str, params: dict[str, Any]):
        length_function = self._resolve_length_function(params, error_code="invalid_splitter_params")

        if strategy == "recursive":
            from rag_lib.chunkers.recursive import RecursiveCharacterTextSplitter

            return RecursiveCharacterTextSplitter(
                chunk_size=params.get("chunk_size", 4000),
                chunk_overlap=params.get("chunk_overlap", 200),
                length_function=length_function,
                separators=params.get("separators"),
                keep_separator=bool(params.get("keep_separator", False)),
                is_separator_regex=bool(params.get("is_separator_regex", False)),
            )
        if strategy == "token":
            from rag_lib.chunkers.token import TokenTextSplitter

            return TokenTextSplitter(
                chunk_size=params.get("chunk_size", 4000),
                chunk_overlap=params.get("chunk_overlap", 200),
                length_function=length_function,
                model_name=params.get("model_name", "cl100k_base"),
                encoding_name=params.get("encoding_name"),
            )
        if strategy == "sentence":
            from rag_lib.chunkers.sentence import SentenceSplitter

            return SentenceSplitter(
                chunk_size=params.get("chunk_size", 4000),
                chunk_overlap=params.get("chunk_overlap", 200),
                length_function=length_function,
                language=params.get("language", "auto"),
            )
        if strategy == "regex":
            from rag_lib.chunkers.regex import RegexSplitter

            pattern = params.get("pattern")
            if not pattern:
                raise api_error(400, "invalid_splitter_params", "regex split strategy requires pattern")
            return RegexSplitter(
                pattern=pattern,
                chunk_size=params.get("chunk_size", 4000),
                chunk_overlap=params.get("chunk_overlap", 200),
                length_function=length_function,
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
                raise api_error(400, "invalid_splitter_params", "regex_hierarchy split strategy requires patterns")
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
                min_chunk_size=int(params.get("min_chunk_size", 0)),
                schema=params.get("schema", "."),
                schema_dialect=self._resolve_schema_dialect(
                    params.get("schema_dialect", "dot_path"),
                    error_code="invalid_splitter_params",
                ),
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
                length_function=length_function,
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

        raise api_error(400, "unsupported_split_strategy", "Unsupported segment split strategy", {"strategy": strategy})

    def _resolve_length_function(self, params: dict[str, Any], *, error_code: str) -> Callable[[str], int]:
        mode = str(params.get("length_mode", "string_len")).strip().lower()
        if mode == "string_len":
            return len
        if mode != "token_len":
            raise api_error(
                400,
                error_code,
                "length_mode must be string_len or token_len",
                {"length_mode": mode, "allowed": ["string_len", "token_len"]},
            )

        cfg = params.get("length_mode_config")
        if cfg is not None and not isinstance(cfg, dict):
            raise api_error(400, error_code, "length_mode_config must be an object", {"length_mode_config": cfg})
        cfg = cfg or {}

        encoding_name = cfg.get("encoding_name") or params.get("encoding_name")
        model_name = cfg.get("model_name") or params.get("model_name")
        default_encoding = "cl100k_base"

        try:
            import tiktoken
        except Exception as exc:
            raise api_error(
                424,
                "missing_dependency",
                "token_len length_mode requires tiktoken dependency",
                {"dependency": "tiktoken"},
            ) from exc

        try:
            if encoding_name:
                encoding = tiktoken.get_encoding(str(encoding_name))
            elif model_name:
                encoding = tiktoken.encoding_for_model(str(model_name))
            else:
                encoding = tiktoken.get_encoding(default_encoding)
        except Exception as exc:
            raise api_error(
                400,
                error_code,
                "Invalid token_len configuration for length_mode",
                {
                    "encoding_name": encoding_name,
                    "model_name": model_name,
                    "default_encoding": default_encoding,
                    "error": str(exc),
                },
            ) from exc

        def _token_len(value: str) -> int:
            return len(encoding.encode(value or ""))

        return _token_len

    def _resolve_schema_dialect(self, raw_value: Any, *, error_code: str):
        from rag_lib.loaders.data_loaders import SchemaDialect

        candidate = SchemaDialect.DOT_PATH.value if raw_value in {None, ""} else str(raw_value)
        try:
            return SchemaDialect(candidate)
        except Exception as exc:
            raise api_error(
                400,
                error_code,
                "schema_dialect must be a supported SchemaDialect value",
                {"schema_dialect": raw_value, "allowed": [SchemaDialect.DOT_PATH.value]},
            ) from exc

    def _build_table_summarizer(self, cfg: dict[str, Any] | None):
        if not cfg:
            return None

        kind = str((cfg or {}).get("type", "mock")).lower()
        if kind == "mock":
            from rag_lib.summarizers.table import MockTableSummarizer

            return MockTableSummarizer()

        if kind != "llm":
            raise api_error(400, "invalid_splitter_params", "table_summarizer.type must be mock or llm")

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
        return LLMTableSummarizer(
            llm=llm,
            prompt_template=cfg.get("prompt_template"),
            soft_max_chars=cfg.get("soft_max_chars"),
        )

    async def list_segment_sets(self, project_id: str) -> list[SegmentSetVersion]:
        stmt = (
            select(SegmentSetVersion)
            .where(SegmentSetVersion.project_id == project_id, SegmentSetVersion.is_deleted.is_(False))
            .order_by(SegmentSetVersion.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_segment_set(self, segment_set_id: str) -> SegmentSetVersion:
        row = await self.session.get(SegmentSetVersion, segment_set_id)
        if not row or row.is_deleted:
            raise api_error(404, "segment_set_not_found", "Segment set not found", {"segment_set_version_id": segment_set_id})
        return row

    async def list_items(self, segment_set_id: str) -> list[SegmentItem]:
        stmt = (
            select(SegmentItem)
            .where(SegmentItem.segment_set_version_id == segment_set_id)
            .order_by(SegmentItem.position.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_items(self, segment_set_id: str) -> int:
        stmt = select(func.count(SegmentItem.id)).where(SegmentItem.segment_set_version_id == segment_set_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def get_document_set(self, document_set_id: str) -> DocumentSetVersion:
        row = await self.session.get(DocumentSetVersion, document_set_id)
        if not row or row.is_deleted:
            raise api_error(
                404,
                "document_set_not_found",
                "Document set not found",
                {"document_set_version_id": document_set_id},
            )
        return row

    async def list_document_items(self, document_set_id: str) -> list[DocumentItem]:
        stmt = (
            select(DocumentItem)
            .where(DocumentItem.document_set_version_id == document_set_id)
            .order_by(DocumentItem.position.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def clone_patch_item(self, segment_set_id: str, item_id: str, patch: dict, params: dict) -> SegmentSetVersion:
        original_set = await self.get_segment_set(segment_set_id)
        items = await self.list_items(segment_set_id)
        target = next((it for it in items if it.item_id == item_id), None)
        if not target:
            raise api_error(404, "segment_item_not_found", "Segment item not found", {"item_id": item_id})

        await self.session.execute(
            update(SegmentSetVersion)
            .where(
                SegmentSetVersion.project_id == original_set.project_id,
                SegmentSetVersion.document_version_id == original_set.document_version_id,
                SegmentSetVersion.is_active.is_(True),
            )
            .values(is_active=False)
        )

        cloned = SegmentSetVersion(
            project_id=original_set.project_id,
            document_version_id=original_set.document_version_id,
            parent_segment_set_version_id=original_set.segment_set_version_id,
            params_json={**(original_set.params_json or {}), "clone_patch": params},
            input_refs_json={"parent_segment_set_version_id": original_set.segment_set_version_id, "patched_item_id": item_id},
            producer_type=original_set.producer_type,
            producer_version=original_set.producer_version,
            is_active=True,
        )
        self.session.add(cloned)
        await self.session.flush()

        new_rows: list[SegmentItem] = []
        snapshot: list[dict[str, Any]] = []
        for i, src in enumerate(items):
            content = patch.get("content", src.content) if src.item_id == item_id else src.content
            metadata = patch.get("metadata", src.metadata_json) if src.item_id == item_id else src.metadata_json
            row = SegmentItem(
                segment_set_version_id=cloned.segment_set_version_id,
                item_id=src.item_id,
                position=i,
                content=content,
                metadata_json=metadata,
                parent_id=patch.get("parent_id", src.parent_id) if src.item_id == item_id else src.parent_id,
                level=int(patch.get("level", src.level)) if src.item_id == item_id else src.level,
                path_json=patch.get("path", src.path_json) if src.item_id == item_id else src.path_json,
                type=patch.get("type", src.type) if src.item_id == item_id else src.type,
                original_format=patch.get("original_format", src.original_format) if src.item_id == item_id else src.original_format,
            )
            new_rows.append(row)
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

        self.session.add_all(new_rows)

        key = f"projects/{cloned.project_id}/segments/{cloned.segment_set_version_id}/segments.json"
        cloned.artifact_uri = object_store.put_json(key, snapshot)

        await self.session.commit()
        await self.session.refresh(cloned)
        return cloned
