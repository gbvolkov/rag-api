import copy
import os
import tempfile
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_feature, require_module
from app.core.config import settings
from app.core.errors import api_error
from app.core.mime_utils import normalize_mime
from app.models import Document, DocumentItem, DocumentSetVersion, DocumentVersion, Project
from app.storage.keys import uri_to_key
from app.storage.object_store import object_store


SUPPORTED_LOADERS = {
    "pdf",
    "miner_u",
    "pymupdf",
    "docx",
    "html",
    "csv",
    "excel",
    "json",
    "text",
    "table",
    "regex",
    "web",
    "web_async",
}
URL_LOADERS = {"web", "web_async"}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _document_to_row(doc: object, position: int) -> dict[str, Any]:
    metadata = dict(getattr(doc, "metadata", {}) or {})
    output_format = metadata.get("output_format") or metadata.get("original_format") or "text"
    return {
        "item_id": str(uuid.uuid4()),
        "position": position,
        "content": getattr(doc, "page_content", ""),
        "metadata_json": metadata,
        "original_format": str(output_format or "text"),
    }


class DocumentLoadService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def load_from_document_version(
        self,
        *,
        version_id: str,
        loader_type: str | None,
        loader_params: dict[str, Any] | None,
    ) -> DocumentSetVersion:
        doc_version = await self.session.get(DocumentVersion, version_id)
        if not doc_version or doc_version.is_deleted:
            raise api_error(404, "document_version_not_found", "Document version not found", {"version_id": version_id})

        document = await self.session.get(Document, doc_version.document_id)
        if not document or document.is_deleted:
            raise api_error(404, "document_not_found", "Document not found", {"document_id": doc_version.document_id})

        requested_params = dict(loader_params or {})
        doc_class, resolved_loader_type, resolved_loader_params, policy_info = self._resolve_loader_for_source(
            source_kind="file",
            mime=document.mime,
            filename=document.filename,
            requested_loader_type=loader_type,
            requested_loader_params=requested_params,
        )

        key = uri_to_key(document.storage_uri)
        content = object_store.get_bytes(key)
        docs = self._load_from_file_bytes(
            content=content,
            filename=document.filename,
            loader_type=resolved_loader_type,
            loader_params=resolved_loader_params,
        )
        return await self._create_document_set(
            project_id=document.project_id,
            document_version_id=version_id,
            documents=docs,
            params={
                "document_class": doc_class,
                "loader_policy": policy_info,
                "loader_type": resolved_loader_type,
                "loader_params": resolved_loader_params,
                "requested_loader_type": loader_type,
                "requested_loader_params": requested_params,
            },
            input_refs={"document_version_id": version_id},
        )

    async def load_from_url(
        self,
        *,
        project_id: str,
        loader_type: str | None,
        loader_params: dict[str, Any] | None,
    ) -> DocumentSetVersion:
        project = await self.session.get(Project, project_id)
        if not project or project.is_deleted:
            raise api_error(404, "project_not_found", "Project not found", {"project_id": project_id})

        requested_params = dict(loader_params or {})
        url = str(requested_params.get("url") or "").strip()
        if not url:
            raise api_error(400, "invalid_loader_params", "loader_params.url is required for URL loading")

        doc_class, resolved_loader_type, resolved_loader_params, policy_info = self._resolve_loader_for_source(
            source_kind="url",
            mime=None,
            filename=None,
            requested_loader_type=loader_type,
            requested_loader_params=requested_params,
        )
        docs, stats, errors = await self._load_from_url_params(
            loader_type=resolved_loader_type,
            loader_params=resolved_loader_params,
        )
        return await self._create_document_set(
            project_id=project_id,
            document_version_id=None,
            documents=docs,
            params={
                "document_class": doc_class,
                "loader_policy": policy_info,
                "loader_type": resolved_loader_type,
                "loader_params": resolved_loader_params,
                "requested_loader_type": loader_type,
                "requested_loader_params": requested_params,
                "web_stats": stats,
                "web_errors": errors,
            },
            input_refs={"url": url},
        )

    async def list_document_sets(self, project_id: str) -> list[DocumentSetVersion]:
        stmt = (
            select(DocumentSetVersion)
            .where(DocumentSetVersion.project_id == project_id, DocumentSetVersion.is_deleted.is_(False))
            .order_by(DocumentSetVersion.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_document_set(self, document_set_id: str) -> DocumentSetVersion:
        row = await self.session.get(DocumentSetVersion, document_set_id)
        if not row or row.is_deleted:
            raise api_error(404, "document_set_not_found", "Document set not found", {"document_set_version_id": document_set_id})
        return row

    async def list_items(self, document_set_id: str) -> list[DocumentItem]:
        stmt = (
            select(DocumentItem)
            .where(DocumentItem.document_set_version_id == document_set_id)
            .order_by(DocumentItem.position.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_items(self, document_set_id: str) -> int:
        stmt = select(func.count(DocumentItem.id)).where(DocumentItem.document_set_version_id == document_set_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    def _resolve_loader_for_source(
        self,
        *,
        source_kind: str,
        mime: str | None,
        filename: str | None,
        requested_loader_type: str | None,
        requested_loader_params: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        document_class = self._resolve_document_class(source_kind=source_kind, mime=mime, filename=filename)
        class_rule = dict(settings.loader_policy_class_rules.get(document_class) or {})
        if not class_rule:
            raise api_error(
                400,
                "unsupported_document_class",
                "Document class has no loader policy",
                {"document_class": document_class},
            )

        allowed_loaders = [str(item).lower() for item in class_rule.get("allowed_loaders", [])]
        default_loader = str(class_rule.get("default_loader") or "").strip().lower()
        selected_loader = str(requested_loader_type or default_loader).strip().lower()
        if not selected_loader:
            raise api_error(
                400,
                "loader_resolution_failed",
                "Failed to resolve loader from policy",
                {"document_class": document_class},
            )
        if selected_loader not in SUPPORTED_LOADERS:
            raise api_error(400, "unsupported_loader", "Unsupported loader type", {"loader_type": selected_loader})
        if selected_loader not in allowed_loaders:
            raise api_error(
                400,
                "loader_not_allowed_for_document_class",
                "Loader is not allowed for resolved document class",
                {"loader_type": selected_loader, "document_class": document_class, "allowed_loaders": allowed_loaders},
            )

        if source_kind == "file" and selected_loader in URL_LOADERS:
            raise api_error(
                400,
                "loader_not_allowed_for_source",
                "URL loaders cannot be used with file document versions",
                {"loader_type": selected_loader, "source_kind": source_kind},
            )
        if source_kind == "url" and selected_loader not in URL_LOADERS:
            raise api_error(
                400,
                "loader_not_allowed_for_source",
                "Only web/web_async loaders can be used with URL source",
                {"loader_type": selected_loader, "source_kind": source_kind},
            )

        default_params = dict(settings.loader_policy_loader_defaults.get(selected_loader) or {})
        resolved_loader_params = _deep_merge(default_params, dict(requested_loader_params or {}))
        if selected_loader == "regex":
            raw_patterns = resolved_loader_params.get("patterns")
            if not isinstance(raw_patterns, list) or not raw_patterns:
                raise api_error(
                    400,
                    "invalid_loader_params",
                    "regex loader requires non-empty patterns list",
                    {"loader_type": "regex"},
                )
        return document_class, selected_loader, resolved_loader_params, {
            "default_loader": default_loader,
            "allowed_loaders": allowed_loaders,
        }

    def _resolve_document_class(self, *, source_kind: str, mime: str | None, filename: str | None) -> str:
        if source_kind == "url":
            return "web"

        normalized_mime = normalize_mime(mime)
        extension = (os.path.splitext(filename or "")[1] or "").lower()
        mime_map = settings.loader_policy_mime_class_map or {}
        extension_map = settings.loader_policy_extension_class_map or {}
        document_class = mime_map.get(normalized_mime) or extension_map.get(extension)
        if not document_class:
            raise api_error(
                400,
                "unsupported_document_class",
                "Unable to resolve document class from MIME/extension policy",
                {"mime": normalized_mime, "extension": extension},
            )
        return str(document_class)

    def _load_from_file_bytes(
        self,
        *,
        content: bytes,
        filename: str,
        loader_type: str,
        loader_params: dict[str, Any],
    ) -> list[object]:
        suffix = os.path.splitext(filename)[1] or ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            path = tmp.name
        try:
            if loader_type == "pdf":
                from rag_lib.loaders.pdf import PDFLoader

                summarizer = None
                if loader_params.get("summarize_tables", False):
                    summarizer = self._build_table_summarizer(loader_params.get("table_summarizer"), error_code="invalid_loader_params")
                loader = PDFLoader(
                    file_path=path,
                    parse_mode=loader_params.get("parse_mode", "text"),
                    backend=loader_params.get("backend"),
                    summarizer=summarizer,
                )
            elif loader_type == "miner_u":
                require_feature(
                    settings.feature_enable_miner_u,
                    "miner_u",
                    hint="Set FEATURE_ENABLE_MINER_U=true to enable MinerU loader.",
                )
                require_module("magic_pdf", "miner_u", install_hint="Install optional dependency 'magic-pdf'.")
                from rag_lib.loaders.miner_u import MinerULoader

                loader = MinerULoader(
                    file_path=path,
                    parse_mode=loader_params.get("parse_mode", "auto"),
                    backend=loader_params.get("backend"),
                    lang=loader_params.get("lang"),
                    server_url=loader_params.get("server_url"),
                    start_page=loader_params.get("start_page"),
                    end_page=loader_params.get("end_page"),
                    parse_formula=loader_params.get("parse_formula"),
                    parse_table=loader_params.get("parse_table"),
                    device=loader_params.get("device"),
                    vram=loader_params.get("vram"),
                    source=loader_params.get("source"),
                    timeout_seconds=int(loader_params.get("timeout_seconds", 600)),
                    keep_temp_artifacts=bool(loader_params.get("keep_temp_artifacts", False)),
                )
            elif loader_type == "docx":
                from rag_lib.loaders.docx import DocXLoader

                loader = DocXLoader(file_path=path)
            elif loader_type == "pymupdf":
                from rag_lib.loaders.pymupdf import PyMuPDFLoader

                loader = PyMuPDFLoader(file_path=path, output_format=loader_params.get("output_format", "markdown"))
            elif loader_type == "html":
                from rag_lib.loaders.html import HTMLLoader

                loader = HTMLLoader(file_path=path, output_format=loader_params.get("output_format", "markdown"))
            elif loader_type == "csv":
                from rag_lib.loaders.csv_excel import CSVLoader

                loader = CSVLoader(
                    file_path=path,
                    output_format=loader_params.get("output_format", "markdown"),
                    delimiter=loader_params.get("delimiter"),
                )
            elif loader_type == "excel":
                from rag_lib.loaders.csv_excel import ExcelLoader

                summarizer = None
                if loader_params.get("summarize_tables", False):
                    summarizer = self._build_table_summarizer(loader_params.get("table_summarizer"), error_code="invalid_loader_params")
                loader = ExcelLoader(
                    file_path=path,
                    output_format=loader_params.get("output_format", "markdown"),
                    delimiter=loader_params.get("delimiter", ","),
                    summarizer=summarizer,
                )
            elif loader_type == "json":
                from rag_lib.loaders.data_loaders import JsonLoader

                loader = JsonLoader(
                    file_path=path,
                    output_format=loader_params.get("output_format", "json"),
                    schema=loader_params.get("schema", "."),
                    schema_dialect=self._resolve_schema_dialect(
                        loader_params.get("schema_dialect", "dot_path"),
                        error_code="invalid_loader_params",
                    ),
                    ensure_ascii=bool(loader_params.get("ensure_ascii", False)),
                )
            elif loader_type == "text":
                from rag_lib.loaders.data_loaders import TextLoader

                loader = TextLoader(file_path=path)
            elif loader_type == "table":
                from rag_lib.loaders.data_loaders import TableLoader

                loader = TableLoader(file_path=path)
            elif loader_type == "regex":
                from rag_lib.loaders.regex import RegexHierarchyLoader

                raw_patterns = loader_params.get("patterns")
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
            documents = loader.load()
            return list(documents or [])
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    async def _load_from_url_params(
        self,
        *,
        loader_type: str,
        loader_params: dict[str, Any],
    ) -> tuple[list[object], dict[str, Any], list[dict[str, Any]]]:
        cleanup_config = self._build_web_cleanup_config(loader_params.get("cleanup_config"))
        playwright_navigation_config = self._build_playwright_navigation_config(loader_params.get("playwright_navigation_config"))
        playwright_extraction_config = self._build_playwright_extraction_config(loader_params.get("playwright_extraction_config"))
        if loader_type == "web":
            from rag_lib.loaders.web import WebLoader

            loader = WebLoader(
                url=loader_params.get("url"),
                depth=int(loader_params.get("depth", 0)),
                output_format=loader_params.get("output_format", "markdown"),
                fetch_mode=loader_params.get("fetch_mode", "requests"),
                crawl_scope=loader_params.get("crawl_scope", "same_host"),
                allowed_domains=loader_params.get("allowed_domains"),
                follow_download_links=bool(loader_params.get("follow_download_links", False)),
                request_timeout_seconds=float(loader_params.get("request_timeout_seconds", 20.0)),
                playwright_timeout_ms=int(loader_params.get("playwright_timeout_ms", 30000)),
                playwright_headless=bool(loader_params.get("playwright_headless", True)),
                ignore_https_errors=bool(loader_params.get("ignore_https_errors", False)),
                user_agent=loader_params.get("user_agent", "rag-lib-webloader/1.0"),
                max_pages=loader_params.get("max_pages"),
                retry_attempts=int(loader_params.get("retry_attempts", 1)),
                continue_on_error=bool(loader_params.get("continue_on_error", True)),
                login_url=loader_params.get("login_url"),
                cleanup_config=cleanup_config,
                playwright_visible=loader_params.get("playwright_visible"),
                playwright_extraction_config=playwright_extraction_config,
                playwright_navigation_config=playwright_navigation_config,
            )
            documents = loader.load()
            return list(documents or []), dict(loader.last_stats or {}), list(loader.last_errors or [])

        from rag_lib.loaders.web_async import AsyncWebLoader

        loader = AsyncWebLoader(
            url=loader_params.get("url"),
            depth=int(loader_params.get("depth", 0)),
            output_format=loader_params.get("output_format", "markdown"),
            fetch_mode=loader_params.get("fetch_mode", "requests"),
            crawl_scope=loader_params.get("crawl_scope", "same_host"),
            allowed_domains=loader_params.get("allowed_domains"),
            follow_download_links=bool(loader_params.get("follow_download_links", False)),
            request_timeout_seconds=float(loader_params.get("request_timeout_seconds", 20.0)),
            playwright_timeout_ms=int(loader_params.get("playwright_timeout_ms", 30000)),
            playwright_headless=bool(loader_params.get("playwright_headless", True)),
            ignore_https_errors=bool(loader_params.get("ignore_https_errors", False)),
            user_agent=loader_params.get("user_agent", "rag-lib-webloader/1.0"),
            max_pages=loader_params.get("max_pages"),
            retry_attempts=int(loader_params.get("retry_attempts", 1)),
            max_concurrency=int(loader_params.get("max_concurrency", 5)),
            continue_on_error=bool(loader_params.get("continue_on_error", True)),
            login_url=loader_params.get("login_url"),
            cleanup_config=cleanup_config,
            playwright_visible=loader_params.get("playwright_visible"),
            playwright_extraction_config=playwright_extraction_config,
            playwright_navigation_config=playwright_navigation_config,
        )
        documents = await loader.load()
        return list(documents or []), dict(loader.last_stats or {}), list(loader.last_errors or [])

    async def _create_document_set(
        self,
        *,
        project_id: str,
        document_version_id: str | None,
        documents: list[object],
        params: dict[str, Any],
        input_refs: dict[str, Any],
    ) -> DocumentSetVersion:
        if document_version_id:
            await self.session.execute(
                update(DocumentSetVersion)
                .where(
                    DocumentSetVersion.document_version_id == document_version_id,
                    DocumentSetVersion.is_active.is_(True),
                )
                .values(is_active=False)
            )

        document_set = DocumentSetVersion(
            project_id=project_id,
            document_version_id=document_version_id,
            params_json=params,
            input_refs_json=input_refs,
            producer_type="rag_lib",
            producer_version=settings.rag_lib_producer_version,
            is_active=True,
        )
        self.session.add(document_set)
        await self.session.flush()

        rows: list[DocumentItem] = []
        snapshot: list[dict[str, Any]] = []
        for i, doc in enumerate(documents):
            mapped = _document_to_row(doc, i)
            row = DocumentItem(document_set_version_id=document_set.document_set_version_id, **mapped)
            rows.append(row)
            snapshot.append(
                {
                    "item_id": row.item_id,
                    "position": row.position,
                    "content": row.content,
                    "metadata": row.metadata_json,
                    "original_format": row.original_format,
                }
            )

        self.session.add_all(rows)
        key = f"projects/{project_id}/document_sets/{document_set.document_set_version_id}/documents.json"
        artifact_uri = object_store.put_json(key, snapshot)
        document_set.artifact_uri = artifact_uri

        mirror_key = f"projects/{project_id}/metadata_mirror/document_set/{document_set.document_set_version_id}.json"
        object_store.put_json(
            mirror_key,
            {
                "document_set_version_id": document_set.document_set_version_id,
                "project_id": document_set.project_id,
                "document_version_id": document_set.document_version_id,
                "params": document_set.params_json,
                "input_refs": document_set.input_refs_json,
                "artifact_uri": document_set.artifact_uri,
            },
        )

        await self.session.commit()
        await self.session.refresh(document_set)
        return document_set

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

    def _build_table_summarizer(self, cfg: dict | None, *, error_code: str):
        if not cfg:
            return None
        kind = str((cfg or {}).get("type", "mock")).lower()
        if kind == "mock":
            from rag_lib.summarizers.table import MockTableSummarizer

            return MockTableSummarizer()
        if kind != "llm":
            raise api_error(400, error_code, "table_summarizer.type must be mock or llm")

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

    def _build_web_cleanup_config(self, cfg: Any):
        if cfg is None:
            return None
        if not isinstance(cfg, dict):
            return cfg
        try:
            from rag_lib.loaders.web_common import WebCleanupConfig

            return WebCleanupConfig(
                ignored_classes=tuple(cfg.get("ignored_classes", ()) or ()),
                non_recursive_classes=tuple(cfg.get("non_recursive_classes", ()) or ()),
                navigation_classes=tuple(cfg.get("navigation_classes", ()) or ()),
                navigation_styles=tuple(cfg.get("navigation_styles", ()) or ()),
                navigation_texts=tuple(cfg.get("navigation_texts", ()) or ()),
                duplicate_tags=tuple(cfg.get("duplicate_tags", ()) or ()),
            )
        except Exception as exc:
            raise api_error(400, "invalid_loader_params", "Invalid cleanup_config payload", {"error": str(exc)}) from exc

    def _build_playwright_navigation_config(self, cfg: Any):
        if cfg is None:
            return None
        if not isinstance(cfg, dict):
            return cfg
        try:
            from rag_lib.loaders.web_playwright_extractors import PlaywrightNavigationConfig

            return PlaywrightNavigationConfig(**cfg)
        except Exception as exc:
            raise api_error(
                400,
                "invalid_loader_params",
                "Invalid playwright_navigation_config payload",
                {"error": str(exc)},
            ) from exc

    def _build_playwright_extraction_config(self, cfg: Any):
        if cfg is None:
            return None
        if not isinstance(cfg, dict):
            return cfg
        try:
            from rag_lib.loaders.web_playwright_extractors import (
                PlaywrightExtractionConfig,
                PlaywrightProfileConfig,
            )

            payload = dict(cfg)
            profiles = payload.get("profiles")
            if isinstance(profiles, list):
                payload["profiles"] = tuple(PlaywrightProfileConfig(**item) for item in profiles)
            return PlaywrightExtractionConfig(**payload)
        except Exception as exc:
            raise api_error(
                400,
                "invalid_loader_params",
                "Invalid playwright_extraction_config payload",
                {"error": str(exc)},
            ) from exc
