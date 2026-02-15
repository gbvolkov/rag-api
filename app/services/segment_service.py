import os
import tempfile
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_feature, require_module
from app.core.config import settings
from app.core.errors import api_error
from app.models import Document, DocumentVersion, SegmentItem, SegmentSetVersion
from app.storage.keys import uri_to_key
from app.storage.object_store import object_store


def _segment_to_row(seg: object, position: int) -> dict:
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

    async def create_from_document_version(self, version_id: str, loader_type: str, loader_params: dict, source_text: str | None = None) -> SegmentSetVersion:
        doc_version = await self.session.get(DocumentVersion, version_id)
        if not doc_version or doc_version.is_deleted:
            raise api_error(404, "document_version_not_found", "Document version not found", {"version_id": version_id})

        document = await self.session.get(Document, doc_version.document_id)
        if not document or document.is_deleted:
            raise api_error(404, "document_not_found", "Document not found", {"document_id": doc_version.document_id})

        segments = await self._load_segments(document, loader_type, loader_params, source_text)

        return await self.create_derived_from_segments(
            project_id=document.project_id,
            document_version_id=version_id,
            parent_segment_set_version_id=None,
            segments=segments,
            params={"loader_type": loader_type, "loader_params": loader_params, "source_text": bool(source_text)},
            input_refs={"document_version_id": version_id},
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
        snapshot: list[dict] = []
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

        mirror_key = (
            f"projects/{project_id}/metadata_mirror/segment_set/{segment_set.segment_set_version_id}.json"
        )
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

    async def _load_segments(self, document: Document, loader_type: str, loader_params: dict, source_text: str | None) -> list:
        if source_text:
            from rag_lib.core.domain import Segment

            return [Segment(content=source_text)]

        key = uri_to_key(document.storage_uri)
        content = object_store.get_bytes(key)

        suffix = os.path.splitext(document.filename)[1] or ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            path = tmp.name

        try:
            loader_type = loader_type.lower()
            if loader_type == "pdf":
                from rag_lib.loaders.pdf import PDFLoader

                summarizer = None
                if loader_params.get("summarize_tables", False):
                    summarizer = self._build_pdf_summarizer(loader_params.get("table_summarizer", {}))
                loader = PDFLoader(file_path=path, backend=loader_params.get("backend"), summarizer=summarizer)
            elif loader_type == "miner_u":
                require_feature(
                    settings.feature_enable_miner_u,
                    "miner_u",
                    hint="Set FEATURE_ENABLE_MINER_U=true to enable MinerU loader.",
                )
                fallback = bool(loader_params.get("fallback_to_pdf_loader", True))
                try:
                    require_module("magic_pdf", "miner_u", install_hint="Install optional dependency 'magic-pdf'.")
                    from rag_lib.loaders.miner_u import MinerULoader

                    loader = MinerULoader(file_path=path)
                except Exception:
                    if not fallback:
                        raise
                    from rag_lib.loaders.pdf import PDFLoader

                    loader = PDFLoader(file_path=path, backend=loader_params.get("backend"))
            elif loader_type == "docx":
                from rag_lib.loaders.structured import StructuredLoader

                loader = StructuredLoader(
                    file_path=path,
                    regex_patterns=loader_params.get("regex_patterns"),
                    exclude_patterns=loader_params.get("exclude_patterns"),
                    include_parent_content=loader_params.get("include_parent_content", True),
                )
            elif loader_type == "csv":
                from rag_lib.loaders.csv_excel import CSVLoader

                loader = CSVLoader(file_path=path, chunk_size=loader_params.get("chunk_size"))
            elif loader_type == "excel":
                from rag_lib.loaders.csv_excel import ExcelLoader

                loader = ExcelLoader(file_path=path)
            elif loader_type == "json":
                from rag_lib.loaders.data_loaders import JsonLoader

                loader = JsonLoader(file_path=path, jq_schema=loader_params.get("jq_schema", "."))
            elif loader_type == "qa":
                from rag_lib.loaders.data_loaders import QALoader

                loader = QALoader(file_path=path)
            elif loader_type == "table":
                from rag_lib.loaders.data_loaders import TableLoader

                loader = TableLoader(
                    file_path=path,
                    mode=loader_params.get("mode", "row"),
                    group_by=loader_params.get("group_by"),
                )
            elif loader_type == "regex":
                from rag_lib.loaders.regex import RegexHierarchyLoader

                raw_patterns = loader_params.get("patterns")
                if not isinstance(raw_patterns, list) or not raw_patterns:
                    raise api_error(
                        400,
                        "invalid_loader_params",
                        "regex loader requires non-empty patterns list",
                    )

                normalized_patterns = []
                for item in raw_patterns:
                    if isinstance(item, list) and len(item) == 2:
                        normalized_patterns.append((item[0], item[1]))
                    else:
                        normalized_patterns.append(item)

                loader = RegexHierarchyLoader(
                    file_path=path,
                    patterns=normalized_patterns,
                    exclude_patterns=loader_params.get("exclude_patterns"),
                    include_parent_content=loader_params.get("include_parent_content", False),
                )
            else:
                raise api_error(400, "unsupported_loader", "Unsupported loader type", {"loader_type": loader_type})

            return loader.load()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def _build_pdf_summarizer(self, cfg: dict[str, Any]):
        kind = str((cfg or {}).get("type", "mock")).lower()
        if kind == "mock":
            from rag_lib.summarizers.table import MockTableSummarizer

            return MockTableSummarizer()

        if kind != "llm":
            raise api_error(400, "invalid_loader_params", "table_summarizer.type must be mock or llm")

        require_feature(
            settings.feature_enable_llm,
            "llm",
            hint="Set FEATURE_ENABLE_LLM=true and configure provider credentials.",
        )
        from rag_lib.llm.factory import get_llm
        from rag_lib.summarizers.table_llm import LLMTableSummarizer

        try:
            llm = get_llm(
                provider=cfg.get("llm_provider") or settings.llm_provider_default,
                model=cfg.get("model") or settings.llm_model_default,
                temperature=settings.llm_temperature_default if cfg.get("temperature") is None else cfg.get("temperature"),
                streaming=False,
            )
        except Exception as exc:
            raise api_error(424, "missing_dependency", "LLM provider initialization failed", {"error": str(exc)}) from exc
        return LLMTableSummarizer(llm=llm)

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
        snapshot: list[dict] = []
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
