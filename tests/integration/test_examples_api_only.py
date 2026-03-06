import io

import pytest
from langchain_core.documents import Document as LCDocument


class _DummyEmbeddings:
    def __call__(self, text):
        return self.embed_query(text)

    def embed_documents(self, texts):
        return [[float((idx % 7) + 1)] * 8 for idx, _ in enumerate(texts)]

    def embed_query(self, text):
        return [0.5] * 8


@pytest.fixture(autouse=True)
def _stub_embeddings_factory(monkeypatch):
    monkeypatch.setattr(
        "rag_lib.embeddings.factory.create_embeddings_model",
        lambda provider, model_name=None: _DummyEmbeddings(),
    )


def _create_project(client, name: str) -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def _upload_document(client, project_id: str, name: str = "doc.txt", content: bytes = b"alpha beta gamma. delta epsilon.") -> str:
    files = {"file": (name, io.BytesIO(content), "text/plain")}
    upload = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    assert upload.status_code == 200, upload.text
    return upload.json()["document_version"]["version_id"]


def _create_segments_from_version(client, version_id: str, loader_type: str = "text", loader_params: dict | None = None) -> str:
    loaded = client.post(
        f"/api/v1/document_versions/{version_id}/load_documents",
        json={"loader_type": loader_type, "loader_params": loader_params or {}},
    )
    assert loaded.status_code == 200, loaded.text
    document_set_id = loaded.json()["document_set"]["document_set_version_id"]
    resp = client.post(
        f"/api/v1/document_sets/{document_set_id}/segments",
        json={"split_strategy": "identity", "splitter_params": {}, "params": {}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["segment_set"]["segment_set_version_id"]


def _split_segment_set(client, segment_set_id: str, strategy: str = "recursive", splitter_params: dict | None = None) -> str:
    resp = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/split",
        json={"strategy": strategy, "splitter_params": splitter_params or {"chunk_size": 80, "chunk_overlap": 0}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["segment_set"]["segment_set_version_id"]


def test_example_01_text_workflow_e2e_api_only(client):
    project_id = _create_project(client, "ex01-text-workflow")
    version_id = _upload_document(client, project_id, content=b"banking guarantee and warranty terms. finance rules.")
    segment_set_id = _create_segments_from_version(client, version_id, "text")
    source_set_id = _split_segment_set(client, segment_set_id, "recursive", {"chunk_size": 32, "chunk_overlap": 0})

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "ex01-faiss", "provider": "faiss", "index_type": "segment_vectors", "config": {"embedding_provider": "openai"}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"source_set_id": source_set_id, "params": {}, "execution_mode": "sync"},
    )
    assert build.status_code == 200, build.text
    build_id = build.json()["build"]["build_id"]

    ret = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={"query": "banking guarantee", "target": "index_build", "target_id": build_id, "strategy": {"type": "vector", "k": 3}},
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= 1


def test_example_03_graph_workflow_api_only(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "feature_enable_graph", True)

    project_id = _create_project(client, "ex03-graph-workflow")
    version_id = _upload_document(client, project_id, content=b"# Task\nalpha beta\n## Details\ngraph links")
    segment_set_id = _create_segments_from_version(client, version_id, "text")
    source_set_id = _split_segment_set(client, segment_set_id, "regex", {"pattern": " "})

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "ex03-faiss", "provider": "faiss", "index_type": "segment_vectors", "config": {"embedding_provider": "openai"}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    idx_build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"source_set_id": source_set_id, "params": {}, "execution_mode": "sync"},
    )
    assert idx_build.status_code == 200, idx_build.text
    index_build_id = idx_build.json()["build"]["build_id"]

    build = client.post(
        f"/api/v1/projects/{project_id}/graph/builds",
        json={
            "source_type": "segment_set",
            "source_id": segment_set_id,
            "backend": "networkx",
            "extract_entities": False,
            "detect_communities": False,
            "summarize_communities": False,
            "params": {"index_build_id": index_build_id},
            "execution_mode": "sync",
        },
    )
    assert build.status_code == 200, build.text
    graph_build_id = build.json()["build"]["graph_build_id"]

    ret = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "alpha",
            "target": "segment_set",
            "target_id": source_set_id,
            "strategy": {
                "type": "graph",
                "graph_build_id": graph_build_id,
                "mode": "hybrid",
                "enable_keyword_extraction": False,
            },
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["strategy"] == "graph"


def test_example_02_raptor_workflow_api_only(client, monkeypatch):
    from app.core.config import settings
    from app.services import segment_transform_service as sts

    monkeypatch.setattr(settings, "feature_enable_raptor", True)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    monkeypatch.setattr(sts, "require_module", lambda *args, **kwargs: None)
    monkeypatch.setattr(sts.SegmentTransformService, "_get_llm", lambda self, provider, model, temperature: object())

    class _DummyRaptorProcessor:
        def __init__(self, llm, embeddings, max_levels):
            self.max_levels = max_levels

        def process_segments(self, segments):
            return segments

    monkeypatch.setattr("rag_lib.processors.raptor.RaptorProcessor", _DummyRaptorProcessor)
    monkeypatch.setattr("rag_lib.embeddings.factory.create_embeddings_model", lambda provider, model_name: object())

    project_id = _create_project(client, "ex02-raptor-workflow")
    version_id = _upload_document(client, project_id, content=b"raptor hierarchy content")
    segment_set_id = _create_segments_from_version(client, version_id, "text")

    resp = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/raptor",
        json={"execution_mode": "sync", "max_levels": 3, "embedding_provider": "openai"},
    )
    assert resp.status_code == 200, resp.text
    out_set_id = resp.json()["segment_set"]["segment_set_version_id"]
    assert out_set_id

    runs = client.get(f"/api/v1/projects/{project_id}/raptor_runs")
    assert runs.status_code == 200, runs.text
    assert len(runs.json()) >= 1


def test_example_13_dual_storage_api_only(client):
    project_id = _create_project(client, "ex13-dual-storage")
    version_id = _upload_document(client, project_id, content=b"dual storage alpha beta")
    segment_set_id = _create_segments_from_version(client, version_id, "text")
    parent_set_id = _split_segment_set(client, segment_set_id, "regex", {"pattern": " "})
    source_set_id = _split_segment_set(client, parent_set_id, "recursive", {"chunk_size": 24, "chunk_overlap": 0})

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "ex13-faiss", "provider": "faiss", "index_type": "segment_vectors", "config": {"embedding_provider": "openai"}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={
            "source_set_id": source_set_id,
            "parent_set_id": parent_set_id,
            "id_key": "source_segment_item_id",
            "params": {},
            "execution_mode": "sync",
            "doc_store": {"backend": "local_file"},
        },
    )
    assert build.status_code == 200, build.text
    build_id = build.json()["build"]["build_id"]

    ret = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "strategy": {"type": "dual_storage", "vector_search": {"k": 5}, "id_key": "source_segment_item_id"},
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= 1


def test_example_17_web_loader_sync_async_api_only(client, monkeypatch):
    project_id = _create_project(client, "ex17-web-loader")
    
    async def _aload(_self):
        return [LCDocument(page_content="async web content", metadata={"source": "https://example.com/async"})]

    monkeypatch.setattr(
        "rag_lib.loaders.web.WebLoader.load",
        lambda self: [LCDocument(page_content="sync web content", metadata={"source": "https://example.com"})],
    )
    monkeypatch.setattr("rag_lib.loaders.web_async.AsyncWebLoader.load", _aload)

    sync_load = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url",
        json={
            "loader_type": "web",
            "loader_params": {"url": "https://example.com", "depth": 0, "fetch_mode": "requests"},
        },
    )
    assert sync_load.status_code == 200, sync_load.text
    sync_document_set_id = sync_load.json()["document_set"]["document_set_version_id"]
    sync_resp = client.post(
        f"/api/v1/document_sets/{sync_document_set_id}/segments",
        json={"split_strategy": "identity", "splitter_params": {}, "params": {}},
    )
    assert sync_resp.status_code == 200, sync_resp.text
    assert len(sync_resp.json()["items"]) == 1

    async_load = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url",
        json={
            "loader_type": "web_async",
            "loader_params": {"url": "https://example.com/async", "depth": 0, "fetch_mode": "requests"},
        },
    )
    assert async_load.status_code == 200, async_load.text
    async_document_set_id = async_load.json()["document_set"]["document_set_version_id"]
    async_resp = client.post(
        f"/api/v1/document_sets/{async_document_set_id}/segments",
        json={"split_strategy": "identity", "splitter_params": {}, "params": {}},
    )
    assert async_resp.status_code == 200, async_resp.text
    assert len(async_resp.json()["items"]) == 1
