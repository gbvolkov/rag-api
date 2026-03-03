from __future__ import annotations

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

    def create_segments(
        self,
        version_id: str,
        loader_type: str,
        loader_params: dict[str, Any] | None = None,
        split_strategy: str | None = None,
        splitter_params: dict[str, Any] | None = None,
        source_text: str | None = None,
    ):
        payload = {
            "loader_type": loader_type,
            "loader_params": loader_params or {},
            "split_strategy": split_strategy,
            "splitter_params": splitter_params or {},
        }
        if source_text is not None:
            payload["source_text"] = source_text
        return self._request("POST", f"/document_versions/{version_id}/segments", json=payload)

    def create_segments_from_url(
        self,
        project_id: str,
        loader_type: str,
        loader_params: dict[str, Any],
        split_strategy: str | None = None,
        splitter_params: dict[str, Any] | None = None,
    ):
        return self._request(
            "POST",
            f"/projects/{project_id}/segments/url",
            json={
                "loader_type": loader_type,
                "loader_params": loader_params,
                "split_strategy": split_strategy,
                "splitter_params": splitter_params or {},
            },
        )

    def create_chunks(self, segment_set_id: str, strategy: str, chunker_params: dict[str, Any] | None = None):
        return self._request("POST", f"/segment_sets/{segment_set_id}/chunk", json={"strategy": strategy, "chunker_params": chunker_params or {}})

    def create_chunks_from_chunk_set(self, chunk_set_id: str, strategy: str, chunker_params: dict[str, Any] | None = None):
        return self._request("POST", f"/chunk_sets/{chunk_set_id}/chunk", json={"strategy": strategy, "chunker_params": chunker_params or {}})

    def create_index(self, project_id: str, name: str, provider: str, config: dict[str, Any] | None = None, params: dict[str, Any] | None = None):
        return self._request(
            "POST",
            f"/projects/{project_id}/indexes",
            json={"name": name, "provider": provider, "index_type": "chunk_vectors", "config": config or {}, "params": params or {}},
        )

    def create_index_build(
        self,
        index_id: str,
        chunk_set_version_id: str,
        execution_mode: str = "sync",
        params: dict[str, Any] | None = None,
        doc_store: dict[str, Any] | None = None,
    ):
        payload: dict[str, Any] = {
            "chunk_set_version_id": chunk_set_version_id,
            "execution_mode": execution_mode,
            "params": params or {},
        }
        if doc_store is not None:
            payload["doc_store"] = doc_store
        return self._request(
            "POST",
            f"/indexes/{index_id}/builds",
            json=payload,
        )

    def create_graph_build(self, project_id: str, source_type: str, source_id: str, execution_mode: str = "sync", backend: str = "networkx", params: dict[str, Any] | None = None):
        payload = {"source_type": source_type, "source_id": source_id, "backend": backend, "execution_mode": execution_mode, "extract_entities": False, "detect_communities": False, "summarize_communities": False}
        if params:
            payload.update(params)
        return self._request("POST", f"/projects/{project_id}/graph/builds", json=payload)

    def run_raptor(self, segment_set_id: str, payload: dict[str, Any]):
        return self._request("POST", f"/segment_sets/{segment_set_id}/raptor", json=payload)

    def run_enrich(self, segment_set_id: str, payload: dict[str, Any]):
        return self._request("POST", f"/segment_sets/{segment_set_id}/enrich", json=payload)

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
    monkeypatch.setattr("app.services.segment_service.require_module", lambda *args, **kwargs: None)
    monkeypatch.setattr(sts.SegmentTransformService, "_get_llm", lambda self, provider, model, temperature: object())
    monkeypatch.setattr("rag_lib.llm.factory.create_llm", lambda **kwargs: object())
    monkeypatch.setattr("rag_lib.processors.enricher.SegmentEnricher.enrich", lambda self, segments: segments)
    monkeypatch.setattr("rag_lib.processors.entity_extractor.EntityExtractor.process_segments", lambda self, segments: None)

    async def _graph_ainvoke(_self, query: str):
        return [LCDocument(page_content=f"graph:{query}", metadata={"retrieval_kind": "chunk", "score": 1.0})]

    monkeypatch.setattr("rag_lib.retrieval.graph_retriever.GraphRetriever.ainvoke", _graph_ainvoke)
    async def _query_graph(_self, graph_build_id, project_id, query, mode="hybrid", graph_query_config=None):
        return [LCDocument(page_content=f"graph:{query}", metadata={"retrieval_kind": "chunk", "score": 1.0})]

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
    class _DummyMinerULoader:
        def __init__(self, file_path: str, **kwargs):
            self.file_path = file_path

        def load(self):
            return [LCDocument(page_content="mineru content", metadata={"source": self.file_path, "parser": "MinerU"})]

    monkeypatch.setattr("rag_lib.loaders.miner_u.MinerULoader", _DummyMinerULoader)

    from app.services import chunk_service as chunk_service_module

    class _DummySemanticChunker:
        def split_text(self, text: str):
            return [text[: max(1, len(text) // 2)], text[max(1, len(text) // 2) :]]

    original_build = chunk_service_module.ChunkService._build_chunker

    def patched_build(self, strategy: str, params: dict):
        if strategy == "semantic":
            return _DummySemanticChunker()
        return original_build(self, strategy, params)

    monkeypatch.setattr(chunk_service_module.ChunkService, "_build_chunker", patched_build)


def _run_example(path: Path, local_client):
    namespace = runpy.run_path(str(path))
    return namespace["run_example"](client=local_client)


def test_all_examples_smoke_api_only(client, monkeypatch):
    _setup_feature_mocks(monkeypatch)
    local_client = _LocalApiClient(client)
    examples_dir = Path(__file__).resolve().parents[2] / "examples"

    for filename in EXAMPLE_FILES:
        artifacts = _run_example(examples_dir / filename, local_client)
        assert artifacts["project_id"]
        assert artifacts["status"] in {"ok", "error"}
