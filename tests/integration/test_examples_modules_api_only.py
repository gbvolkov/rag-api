from __future__ import annotations

import os
import runpy
from pathlib import Path
from typing import Any


EXAMPLE_FILES = [
    "01_text_basic.py",
    "02_markdown_enrichment.py",
    "02_markdown_enrichment_vector.py",
    "03_pdf_semantic.py",
    "04_pdf_raptor.py",
    "05_docx_graph.py",
    "06_docx_regex.py",
    "07_csv_table_summary.py",
    "07_md_table_summary.py",
    "08_excel_csv_basic.py",
    "08_excel_md_basic.py",
    "09_json_hybrid.py",
    "10_text_ensemble.py",
    "11_log_regex_loader.py",
    "12_qa_loader.py",
    "13_dual_storage.py",
    "14_mineru_pdf.py",
    "15_pptx_unsupported.py",
    "16_html_html.py",
    "16_html_md.py",
    "17A_web_loader_plantpad.py",
    "17B_web_loader_quotes.py",
    "17C_web_loader_example.py",
    "17_web_loader.py",
]


class _LocalApiClient:
    def __init__(self, client):
        self.client = client
        self._jobs: dict[str, dict[str, Any]] = {}

    def _request(self, method: str, path: str, **kwargs):
        resp = self.client.request(method, f"/api/v1{path}", **kwargs)
        if resp.status_code >= 400:
            from examples.api_client import ApiClientError

            raise ApiClientError(f"{method} {path} failed", status_code=resp.status_code, payload=resp.json())
        if not resp.content:
            return {}
        return resp.json()

    def create_project(self, name: str, description: str = ""):
        return self._request("POST", "/projects", json={"name": name, "description": description, "settings": {}})

    def upload_document(self, project_id: str, file_path: Path, mime: str, parser_params: dict[str, Any] | None = None):
        parser_params = parser_params or {}
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f, mime)}
            data = {"parser_params_json": __import__("json").dumps(parser_params)}
            return self._request("POST", f"/projects/{project_id}/documents", files=files, data=data)

    def load_documents(
        self,
        version_id: str,
        loader_type: str | None = None,
        loader_params: dict[str, Any] | None = None,
    ):
        return self._request(
            "POST",
            f"/document_versions/{version_id}/load_documents",
            json={
                "loader_type": loader_type,
                "loader_params": loader_params or {},
            },
        )

    def load_documents_from_url(
        self,
        project_id: str,
        loader_type: str | None = None,
        loader_params: dict[str, Any] | None = None,
    ):
        return self._request(
            "POST",
            f"/projects/{project_id}/load_documents/url",
            json={
                "loader_type": loader_type,
                "loader_params": loader_params or {},
            },
        )

    def create_segments(
        self,
        document_set_version_id: str,
        split_strategy: str,
        splitter_params: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ):
        return self._request(
            "POST",
            f"/document_sets/{document_set_version_id}/segments",
            json={
                "split_strategy": split_strategy,
                "splitter_params": splitter_params or {},
                "params": params or {},
            },
        )

    def split_segment_set(
        self,
        segment_set_id: str,
        strategy: str,
        splitter_params: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ):
        return self._request(
            "POST",
            f"/segment_sets/{segment_set_id}/split",
            json={
                "strategy": strategy,
                "splitter_params": splitter_params or {},
                "params": params or {},
            },
        )

    def create_index(self, project_id: str, name: str, provider: str, config: dict[str, Any] | None = None, params: dict[str, Any] | None = None):
        return self._request(
            "POST",
            f"/projects/{project_id}/indexes",
            json={"name": name, "provider": provider, "index_type": "segment_vectors", "config": config or {}, "params": params or {}},
        )

    def create_index_build(
        self,
        index_id: str,
        source_set_id: str,
        execution_mode: str = "sync",
        params: dict[str, Any] | None = None,
        parent_set_id: str | None = None,
        id_key: str | None = None,
        doc_store: dict[str, Any] | None = None,
    ):
        payload: dict[str, Any] = {
            "source_set_id": source_set_id,
            "execution_mode": execution_mode,
            "params": params or {},
        }
        if parent_set_id is not None:
            payload["parent_set_id"] = parent_set_id
        if id_key is not None:
            payload["id_key"] = id_key
        if doc_store is not None:
            payload["doc_store"] = doc_store
        return self._request(
            "POST",
            f"/indexes/{index_id}/builds",
            json=payload,
        )

    def create_graph_build(self, project_id: str, source_type: str, source_id: str, execution_mode: str = "sync", backend: str = "networkx", params: dict[str, Any] | None = None):
        payload: dict[str, Any] = {
            "source_type": source_type,
            "source_id": source_id,
            "backend": backend,
            "execution_mode": execution_mode,
            "extract_entities": False,
            "detect_communities": False,
            "summarize_communities": False,
            "params": {},
        }
        extra = dict(params or {})
        top_level_fields = {
            "extract_entities",
            "detect_communities",
            "summarize_communities",
            "llm_provider",
            "llm_model",
            "llm_temperature",
            "search_depth",
        }
        for key in top_level_fields:
            if key in extra:
                payload[key] = extra.pop(key)

        nested = extra.pop("params", None)
        if isinstance(nested, dict):
            payload["params"].update(nested)
        if extra:
            payload["params"].update(extra)
        if payload.get("execution_mode") == "async":
            sync_payload = {**payload, "execution_mode": "sync"}
            sync_result = self._request("POST", f"/projects/{project_id}/graph/builds", json=sync_payload)
            job_id = f"local-graph-job-{len(self._jobs) + 1}"
            graph_build_id = sync_result.get("build", {}).get("graph_build_id")
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "succeeded",
                "result": {"graph_build_id": graph_build_id, "status": "succeeded"},
                "error_message": None,
            }
            return {"mode": "async", "job_id": job_id, "build": sync_result.get("build", {})}
        return self._request("POST", f"/projects/{project_id}/graph/builds", json=payload)

    def run_raptor(self, segment_set_id: str, payload: dict[str, Any]):
        return self._request("POST", f"/segment_sets/{segment_set_id}/raptor", json=payload)

    def run_enrich(self, segment_set_id: str, payload: dict[str, Any]):
        if payload.get("execution_mode") == "async":
            sync_payload = {**payload, "execution_mode": "sync"}
            sync_result = self._request("POST", f"/segment_sets/{segment_set_id}/enrich", json=sync_payload)
            job_id = f"local-enrich-job-{len(self._jobs) + 1}"
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "succeeded",
                "result": {
                    "segment_set_version_id": sync_result["segment_set"]["segment_set_version_id"],
                    "status": "succeeded",
                },
                "error_message": None,
            }
            return {"mode": "async", "job_id": job_id}
        return self._request("POST", f"/segment_sets/{segment_set_id}/enrich", json=payload)

    def get_job(self, job_id: str):
        if job_id in self._jobs:
            return self._jobs[job_id]
        return self._request("GET", f"/jobs/{job_id}")

    def list_raptor_runs(self, project_id: str):
        return self._request("GET", f"/projects/{project_id}/raptor_runs")

    def retrieve(self, project_id: str, payload: dict[str, Any]):
        return self._request("POST", f"/projects/{project_id}/retrieve", json=payload)

    def list_retrieval_runs(self, project_id: str):
        return self._request("GET", f"/projects/{project_id}/retrieval_runs")


def _setup_feature_mocks(monkeypatch):
    from app.core.config import settings
    from app.services import segment_transform_service as sts
    from langchain_core.documents import Document as LCDocument

    monkeypatch.setattr(settings, "feature_enable_graph", True)
    monkeypatch.setattr(settings, "feature_enable_raptor", True)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    monkeypatch.setattr(settings, "feature_enable_miner_u", True)

    monkeypatch.setattr(sts, "require_module", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.document_load_service.require_module", lambda *args, **kwargs: None)
    monkeypatch.setattr(sts.SegmentTransformService, "_get_llm", lambda self, provider, model, temperature: object())
    monkeypatch.setattr("rag_lib.llm.factory.create_llm", lambda **kwargs: object())
    monkeypatch.setattr("rag_lib.processors.enricher.SegmentEnricher.enrich", lambda self, segments: segments)
    monkeypatch.setattr("rag_lib.processors.entity_extractor.EntityExtractor.process_segments", lambda self, segments: None)

    async def _graph_ainvoke(_self, query: str):
        return [LCDocument(page_content=f"graph:{query}", metadata={"retrieval_kind": "segment", "score": 1.0})]

    monkeypatch.setattr("rag_lib.retrieval.graph_retriever.GraphRetriever.ainvoke", _graph_ainvoke)
    async def _query_graph(_self, graph_build_id, project_id, query, mode="hybrid", graph_query_config=None):
        return [LCDocument(page_content=f"graph:{query}", metadata={"retrieval_kind": "segment", "score": 1.0})]

    monkeypatch.setattr("app.services.graph_service.GraphService.query_graph", _query_graph)
    async def _run_vector(_self, project_id: str, request):
        return [LCDocument(page_content=f"vector:{request.query}", metadata={"score": 1.0, "item_id": "v1"})]

    async def _run_dual_storage(_self, project_id: str, request, docs):
        return [LCDocument(page_content=f"dual:{request.query}", metadata={"score": 1.0, "parent_id": "p1"})]

    monkeypatch.setattr("app.services.retrieval_service.RetrievalService._run_vector", _run_vector)
    monkeypatch.setattr("app.services.retrieval_service.RetrievalService._run_dual_storage", _run_dual_storage)

    class _DummyRaptorProcessor:
        def __init__(self, llm, embeddings, max_levels):
            self.max_levels = max_levels

        def process_segments(self, segments):
            return segments

    class _DummyEmbeddings:
        def __call__(self, text):
            return self.embed_query(text)

        def embed_documents(self, texts):
            return [[float((idx % 7) + 1)] * 8 for idx, _ in enumerate(texts)]

        def embed_query(self, text):
            return [0.5] * 8

    monkeypatch.setattr("rag_lib.processors.raptor.RaptorProcessor", _DummyRaptorProcessor)
    monkeypatch.setattr(
        "rag_lib.embeddings.factory.create_embeddings_model",
        lambda provider, model_name=None: _DummyEmbeddings(),
    )
    monkeypatch.setattr("rag_lib.loaders.web.WebLoader.load", lambda self: [LCDocument(page_content="web", metadata={"source": "https://example.com"})])

    async def _aload(_self):
        return [LCDocument(page_content="web-async", metadata={"source": "https://example.com"})]

    monkeypatch.setattr("rag_lib.loaders.web_async.AsyncWebLoader.load", _aload)

    class _DummyPyMuPDFLoader:
        def __init__(self, file_path: str, output_format: str = "markdown"):
            self.file_path = file_path
            self.output_format = output_format

        def load(self):
            return [LCDocument(page_content="pymupdf content", metadata={"source": self.file_path, "output_format": self.output_format})]

    monkeypatch.setattr("rag_lib.loaders.pymupdf.PyMuPDFLoader", _DummyPyMuPDFLoader)

    class _DummyMinerULoader:
        def __init__(self, file_path: str, **kwargs):
            self.file_path = file_path

        def load(self):
            return [LCDocument(page_content="mineru content", metadata={"source": self.file_path, "parser": "MinerU"})]

    monkeypatch.setattr("rag_lib.loaders.miner_u.MinerULoader", _DummyMinerULoader)

    from app.services import segment_service as segment_service_module

    class _DummySemanticChunker:
        def split_text(self, text: str):
            return [text[: max(1, len(text) // 2)], text[max(1, len(text) // 2) :]]

    original_build = segment_service_module.SegmentService._build_splitter

    def patched_build(self, strategy: str, params: dict):
        if strategy == "semantic":
            return _DummySemanticChunker()
        return original_build(self, strategy, params)

    monkeypatch.setattr(segment_service_module.SegmentService, "_build_splitter", patched_build)


def _run_example(path: Path, local_client):
    namespace = runpy.run_path(str(path))
    return namespace["run_example"](client=local_client)


def _selected_example_files() -> list[str]:
    only = os.getenv("EXAMPLE_FILE")
    if not only:
        return EXAMPLE_FILES
    filename = only.strip()
    if filename not in EXAMPLE_FILES:
        raise AssertionError(f"EXAMPLE_FILE must be one of: {', '.join(EXAMPLE_FILES)}")
    return [filename]


def test_all_examples_smoke_api_only(client, monkeypatch):
    _setup_feature_mocks(monkeypatch)
    local_client = _LocalApiClient(client)
    examples_dir = Path(__file__).resolve().parents[2] / "examples"

    for filename in _selected_example_files():
        artifacts = _run_example(examples_dir / filename, local_client)
        assert artifacts["project_id"]
        assert artifacts["status"] in {"ok", "error"}
