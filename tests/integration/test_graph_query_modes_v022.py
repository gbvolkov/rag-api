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


def test_graph_retrieval_modes_matrix(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "feature_enable_graph", True)

    project_id = _create_project(client)
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

