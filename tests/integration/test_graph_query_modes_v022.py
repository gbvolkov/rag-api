import io


def _create_project(client, name: str = "proj-graph-v022") -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def _create_segment_set(client, project_id: str) -> str:
    files = {"file": ("doc.txt", io.BytesIO(b"alpha beta gamma"), "text/plain")}
    upload = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    assert upload.status_code == 200, upload.text
    version_id = upload.json()["document_version"]["version_id"]
    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "text", "loader_params": {}},
    )
    assert seg.status_code == 200, seg.text
    return seg.json()["segment_set"]["segment_set_version_id"]


def _create_index_build(client, project_id: str, segment_set_id: str) -> str:
    chunk = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/chunk",
        json={"strategy": "regex", "chunker_params": {"pattern": " "}},
    )
    assert chunk.status_code == 200, chunk.text
    chunk_set_id = chunk.json()["chunk_set"]["chunk_set_version_id"]

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "graph-faiss", "provider": "faiss", "index_type": "chunk_vectors", "config": {}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": chunk_set_id, "params": {}, "execution_mode": "sync"},
    )
    assert build.status_code == 200, build.text
    return build.json()["build"]["build_id"]


def test_graph_retrieval_modes_matrix(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "feature_enable_graph", True)

    project_id = _create_project(client)
    segment_set_id = _create_segment_set(client, project_id)
    index_build_id = _create_index_build(client, project_id, segment_set_id)

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

    for mode in ["local", "global", "hybrid", "mix"]:
        ret = client.post(
            f"/api/v1/projects/{project_id}/retrieve",
            json={
                "query": "alpha",
                "target": "graph_build",
                "target_id": graph_build_id,
                "strategy": {
                    "type": "graph",
                    "graph_build_id": graph_build_id,
                    "mode": mode,
                    "enable_keyword_extraction": False,
                },
            },
        )
        assert ret.status_code == 200, ret.text
        assert ret.json()["strategy"] == "graph"


def test_graph_query_without_index_build_id_returns_error(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "feature_enable_graph", True)

    project_id = _create_project(client, "proj-graph-no-index")
    segment_set_id = _create_segment_set(client, project_id)

    build = client.post(
        f"/api/v1/projects/{project_id}/graph/builds",
        json={
            "source_type": "segment_set",
            "source_id": segment_set_id,
            "backend": "networkx",
            "extract_entities": False,
            "detect_communities": False,
            "summarize_communities": False,
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
    assert ret.status_code == 400, ret.text
    assert ret.json()["detail"]["code"] == "graph_index_build_required"
