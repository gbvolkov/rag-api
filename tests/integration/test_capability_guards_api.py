import io


def _create_project(client, name: str) -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "description": "d", "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def _create_segment_set(client, project_id: str) -> str:
    files = {"file": ("sample.txt", io.BytesIO(b"alpha beta gamma"), "text/plain")}
    upload = client.post(
        f"/api/v1/projects/{project_id}/documents",
        data={"parser_params_json": '{"parser_type":"text"}'},
        files=files,
    )
    assert upload.status_code == 200, upload.text
    version_id = upload.json()["document_version"]["version_id"]
    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "json", "loader_params": {}, "source_text": "alpha beta gamma"},
    )
    assert seg.status_code == 200, seg.text
    return seg.json()["segment_set"]["segment_set_version_id"]


def test_table_summarize_mock_works_and_llm_is_guarded(client):
    ok = client.post(
        "/api/v1/tables/summarize",
        json={"markdown_table": "|a|b|\n|---|---|\n|1|2|", "summarizer": {"type": "mock"}},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["summary"]

    denied = client.post(
        "/api/v1/tables/summarize",
        json={"markdown_table": "|a|b|\n|---|---|\n|1|2|", "summarizer": {"type": "llm"}},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "capability_disabled"


def test_graph_build_endpoint_is_guarded_when_graph_feature_disabled(client):
    project_id = _create_project(client, "proj-graph-guard")
    resp = client.post(
        f"/api/v1/projects/{project_id}/graph/builds",
        json={"source_type": "segment_set", "source_id": "missing", "execution_mode": "sync"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "capability_disabled"


def test_segment_enrich_and_raptor_are_guarded_when_features_disabled(client):
    project_id = _create_project(client, "proj-segment-guards")
    segment_set_id = _create_segment_set(client, project_id)

    enrich = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/enrich",
        json={"execution_mode": "sync"},
    )
    assert enrich.status_code == 403, enrich.text
    assert enrich.json()["detail"]["code"] == "capability_disabled"

    raptor = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/raptor",
        json={"execution_mode": "sync"},
    )
    assert raptor.status_code == 403, raptor.text
    assert raptor.json()["detail"]["code"] == "capability_disabled"

