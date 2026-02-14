import io
from dataclasses import dataclass

import pytest


@dataclass
class _Hit:
    payload: dict
    score: float


class _DummyQdrantClient:
    def __init__(self, hits):
        self._hits = hits

    def search(self, *args, **kwargs):
        return self._hits


def _create_project_and_artifacts(client, text: str = "alpha beta gamma. delta epsilon."):
    project = client.post("/api/v1/projects", json={"name": "proj-retrieval", "settings": {}})
    assert project.status_code == 200, project.text
    project_id = project.json()["project_id"]

    files = {"file": ("doc.txt", io.BytesIO(b"content"), "text/plain")}
    upload = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    assert upload.status_code == 200, upload.text
    version_id = upload.json()["document_version"]["version_id"]

    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "json", "loader_params": {}, "source_text": text},
    )
    assert seg.status_code == 200, seg.text
    seg_set_id = seg.json()["segment_set"]["segment_set_version_id"]

    chunk = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": "regex", "chunker_params": {"pattern": "\\. "}},
    )
    assert chunk.status_code == 200, chunk.text
    chunk_set_id = chunk.json()["chunk_set"]["chunk_set_version_id"]

    return {
        "project_id": project_id,
        "version_id": version_id,
        "segment_set_id": seg_set_id,
        "chunk_set_id": chunk_set_id,
    }


def _create_faiss_build(client, project_id: str, chunk_set_id: str) -> str:
    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "faiss-idx", "provider": "faiss", "index_type": "chunk_vectors", "config": {}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": chunk_set_id, "params": {}, "execution_mode": "sync"},
    )
    assert build.status_code == 200, build.text
    return build.json()["build"]["build_id"]


@pytest.mark.parametrize(
    "strategy_payload,expected_min",
    [
        ({"type": "bm25", "k": 5}, 0),
        ({"type": "regex", "pattern": "alpha"}, 1),
        ({"type": "fuzzy", "threshold": 50}, 0),
        ({"type": "ensemble", "sources": [{"type": "regex"}, {"type": "fuzzy", "threshold": 50}], "weights": [0.8, 0.2]}, 0),
    ],
)
def test_retrieval_atomic_and_ensemble_strategies(client, strategy_payload: dict, expected_min: int):
    ids = _create_project_and_artifacts(client)

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": ids["chunk_set_id"],
            "persist": False,
            "strategy": strategy_payload,
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= expected_min


def test_retrieval_ensemble_with_default_sources(client):
    ids = _create_project_and_artifacts(client)

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": ids["chunk_set_id"],
            "persist": False,
            "strategy": {"type": "ensemble", "sources": []},
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= 0


def test_retrieval_vector_strategy_targets_faiss_build(client):
    ids = _create_project_and_artifacts(client)
    build_id = _create_faiss_build(client, ids["project_id"], ids["chunk_set_id"])

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "persist": False,
            "strategy": {"type": "vector", "k": 5},
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= 1


def test_retrieval_rerank_strategy_with_monkeypatched_dependencies(client, monkeypatch):
    ids = _create_project_and_artifacts(client)

    class _SimpleRetriever:
        def __init__(self, docs):
            self._docs = docs

        def invoke(self, query: str):
            return self._docs

    def _mock_get_bm25_retriever(docs, k=4):
        return _SimpleRetriever(docs)

    def _mock_create_reranking_retriever(base_retriever_or_list, reranker_model="x", top_n=5, device="cpu"):
        class _RerankRetriever:
            def invoke(self, query: str):
                docs = base_retriever_or_list.invoke(query)
                return docs[:top_n]

        return _RerankRetriever()

    monkeypatch.setattr("rag_lib.retrieval.retrievers.get_bm25_retriever", _mock_get_bm25_retriever)
    monkeypatch.setattr("rag_lib.retrieval.composition.create_reranking_retriever", _mock_create_reranking_retriever)

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": ids["chunk_set_id"],
            "persist": False,
            "strategy": {
                "type": "rerank",
                "base": {"type": "regex", "pattern": "alpha"},
                "model_name": "mock-reranker",
                "top_n": 3,
                "device": "cpu",
            },
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= 1


def test_retrieval_dual_storage_strategy_with_mocked_qdrant(client, monkeypatch):
    ids = _create_project_and_artifacts(client)

    # Create qdrant index and queued build row (without executing background run).
    idx = client.post(
        f"/api/v1/projects/{ids['project_id']}/indexes",
        json={"name": "qdrant-idx", "provider": "qdrant", "index_type": "chunk_vectors", "config": {}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    class _NoopTask:
        def delay(self, *args, **kwargs):
            return None

    monkeypatch.setattr("app.api.api_v1.endpoints.indexes.run_index_build", _NoopTask())

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": ids["chunk_set_id"], "params": {}, "execution_mode": "async"},
    )
    assert build.status_code == 200, build.text
    build_id = build.json()["build"]["build_id"]

    chunk_set = client.get(f"/api/v1/chunk_sets/{ids['chunk_set_id']}")
    assert chunk_set.status_code == 200, chunk_set.text
    first_chunk = chunk_set.json()["items"][0]

    hits = [_Hit(payload={"chunk_item_id": first_chunk["item_id"]}, score=0.91)]
    monkeypatch.setattr("app.services.retrieval_service.get_qdrant_client", lambda: _DummyQdrantClient(hits))

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "persist": False,
            "strategy": {"type": "dual_storage", "vector_search": {"k": 5}, "id_key": "segment_id"},
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= 1


def test_retrieval_qdrant_vector_strategy_with_mocked_qdrant(client, monkeypatch):
    ids = _create_project_and_artifacts(client)

    idx = client.post(
        f"/api/v1/projects/{ids['project_id']}/indexes",
        json={"name": "qdrant-idx2", "provider": "qdrant", "index_type": "chunk_vectors", "config": {}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    class _NoopTask:
        def delay(self, *args, **kwargs):
            return None

    monkeypatch.setattr("app.api.api_v1.endpoints.indexes.run_index_build", _NoopTask())

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": ids["chunk_set_id"], "params": {}, "execution_mode": "async"},
    )
    assert build.status_code == 200, build.text
    build_id = build.json()["build"]["build_id"]

    mocked_payload = {
        "content": "alpha payload",
        "metadata": {"source": "mock"},
        "chunk_item_id": "cid",
        "chunk_set_version_id": ids["chunk_set_id"],
    }
    hits = [_Hit(payload=mocked_payload, score=0.77)]
    monkeypatch.setattr("app.services.retrieval_service.get_qdrant_client", lambda: _DummyQdrantClient(hits))

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "persist": False,
            "strategy": {"type": "vector", "k": 3},
        },
    )
    assert ret.status_code == 200, ret.text
    data = ret.json()
    assert data["total"] == 1
    assert data["items"][0]["page_content"] == "alpha payload"


def test_retrieval_target_segment_set_and_run_lifecycle(client):
    ids = _create_project_and_artifacts(client, text="segment target alpha")

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "segment_set",
            "target_id": ids["segment_set_id"],
            "persist": True,
            "strategy": {"type": "regex", "pattern": "alpha"},
        },
    )
    assert ret.status_code == 200, ret.text
    run_id = ret.json()["run_id"]
    assert run_id

    listed = client.get(f"/api/v1/projects/{ids['project_id']}/retrieval_runs")
    assert listed.status_code == 200
    assert any(r["run_id"] == run_id for r in listed.json())

    fetched = client.get(f"/api/v1/retrieval_runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["run_id"] == run_id

    deleted = client.delete(f"/api/v1/retrieval_runs/{run_id}")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True


def test_retrieval_default_target_uses_latest_active_chunk_set(client):
    ids = _create_project_and_artifacts(client, text="old alpha")

    original_chunk = client.get(f"/api/v1/chunk_sets/{ids['chunk_set_id']}")
    assert original_chunk.status_code == 200, original_chunk.text
    original_item_id = original_chunk.json()["items"][0]["item_id"]

    patched = client.post(
        f"/api/v1/chunk_sets/{ids['chunk_set_id']}/clone_patch_item",
        json={
            "item_id": original_item_id,
            "patch": {"content": "newer unique token"},
            "params": {"source": "test"},
        },
    )
    assert patched.status_code == 200, patched.text

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "unique",
            "target": "chunk_set",
            "persist": False,
            "strategy": {"type": "regex", "pattern": "unique"},
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= 1
    assert all("unique" in item["page_content"] for item in ret.json()["items"])


def test_retrieval_regex_pagination_cursor_contract(client):
    ids = _create_project_and_artifacts(client, text="alpha one. alpha two. alpha three. alpha four. alpha five.")

    page1 = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": ids["chunk_set_id"],
            "persist": False,
            "limit": 2,
            "strategy": {"type": "regex", "pattern": "alpha"},
        },
    )
    assert page1.status_code == 200, page1.text
    p1 = page1.json()
    assert p1["total"] >= 4
    assert len(p1["items"]) == 2
    assert p1["has_more"] is True
    assert p1["next_cursor"]

    page2 = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": ids["chunk_set_id"],
            "persist": False,
            "limit": 2,
            "cursor": p1["next_cursor"],
            "strategy": {"type": "regex", "pattern": "alpha"},
        },
    )
    assert page2.status_code == 200, page2.text
    p2 = page2.json()
    assert len(p2["items"]) == 2


def test_retrieval_vector_accepts_optional_fields_and_paginates(client):
    ids = _create_project_and_artifacts(client, text="alpha one. alpha two. alpha three. alpha four. alpha five.")
    build_id = _create_faiss_build(client, ids["project_id"], ids["chunk_set_id"])

    page1 = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "persist": False,
            "limit": 2,
            "strategy": {"type": "vector", "k": 4, "search_type": "mmr", "score_threshold": 0.0},
        },
    )
    assert page1.status_code == 200, page1.text
    p1 = page1.json()
    assert p1["total"] >= 2
    assert len(p1["items"]) == 2
    assert p1["next_cursor"]
    assert p1["has_more"] is True

    page2 = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "persist": False,
            "limit": 2,
            "cursor": p1["next_cursor"],
            "strategy": {"type": "vector", "k": 4, "search_type": "mmr", "score_threshold": 0.0},
        },
    )
    assert page2.status_code == 200, page2.text
    assert len(page2.json()["items"]) >= 1


def test_retrieval_rerank_with_vector_base_uses_index_build(client):
    ids = _create_project_and_artifacts(client, text="alpha one. alpha two. alpha three.")
    build_id = _create_faiss_build(client, ids["project_id"], ids["chunk_set_id"])

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "persist": False,
            "strategy": {
                "type": "rerank",
                "base": {"type": "vector", "k": 3},
                "model_name": "mock-reranker",
                "top_n": 2,
                "device": "cpu",
            },
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["total"] >= 1


def test_dual_storage_requires_index_build_target(client):
    ids = _create_project_and_artifacts(client)

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": ids["chunk_set_id"],
            "persist": False,
            "strategy": {"type": "dual_storage", "vector_search": {"k": 5}, "id_key": "segment_id"},
        },
    )
    assert ret.status_code == 400


def test_retrieval_unknown_strategy_type_rejected(client):
    ids = _create_project_and_artifacts(client)

    ret = client.post(
        f"/api/v1/projects/{ids['project_id']}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": ids["chunk_set_id"],
            "persist": False,
            "strategy": {"type": "not-a-real-strategy"},
        },
    )
    assert ret.status_code == 422
