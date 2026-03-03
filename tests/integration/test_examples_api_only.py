import io

from langchain_core.documents import Document as LCDocument


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
    resp = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": loader_type, "loader_params": loader_params or {}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["segment_set"]["segment_set_version_id"]


def _create_chunks(client, segment_set_id: str, strategy: str = "recursive", chunker_params: dict | None = None) -> str:
    resp = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/chunk",
        json={"strategy": strategy, "chunker_params": chunker_params or {"chunk_size": 80, "chunk_overlap": 0}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["chunk_set"]["chunk_set_version_id"]


def test_example_01_text_workflow_e2e_api_only(client):
    project_id = _create_project(client, "ex01-text-workflow")
    version_id = _upload_document(client, project_id, content=b"banking guarantee and warranty terms. finance rules.")
    segment_set_id = _create_segments_from_version(client, version_id, "text")
    chunk_set_id = _create_chunks(client, segment_set_id, "recursive", {"chunk_size": 32, "chunk_overlap": 0})

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "ex01-faiss", "provider": "faiss", "index_type": "chunk_vectors", "config": {"embedding_provider": "mock"}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": chunk_set_id, "params": {}, "execution_mode": "sync"},
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
    chunk_set_id = _create_chunks(client, segment_set_id, "regex", {"pattern": " "})

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "ex03-faiss", "provider": "faiss", "index_type": "chunk_vectors", "config": {"embedding_provider": "mock"}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    idx_build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": chunk_set_id, "params": {}, "execution_mode": "sync"},
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
            "target": "graph_build",
            "target_id": graph_build_id,
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
        json={"execution_mode": "sync", "max_levels": 3, "embedding_provider": "mock"},
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
    chunk_set_id = _create_chunks(client, segment_set_id, "regex", {"pattern": " "})

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "ex13-faiss", "provider": "faiss", "index_type": "chunk_vectors", "config": {"embedding_provider": "mock"}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={
            "chunk_set_version_id": chunk_set_id,
            "params": {},
            "execution_mode": "sync",
            "doc_store": {"source": "auto", "id_key": "parent_id"},
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
            "strategy": {"type": "dual_storage", "vector_search": {"k": 5}, "id_key": "parent_id"},
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

    sync_resp = client.post(
        f"/api/v1/projects/{project_id}/segments/url",
        json={
            "loader_type": "web",
            "loader_params": {"url": "https://example.com", "depth": 0, "fetch_mode": "requests"},
        },
    )
    assert sync_resp.status_code == 200, sync_resp.text
    assert len(sync_resp.json()["items"]) == 1

    async_resp = client.post(
        f"/api/v1/projects/{project_id}/segments/url",
        json={
            "loader_type": "web_async",
            "loader_params": {"url": "https://example.com/async", "depth": 0, "fetch_mode": "requests"},
        },
    )
    assert async_resp.status_code == 200, async_resp.text
    assert len(async_resp.json()["items"]) == 1
