import io


def _create_project(client, name: str = "proj-loader-v022") -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def _upload_text_doc(client, project_id: str, content: bytes = b"alpha beta gamma") -> str:
    files = {"file": ("doc.txt", io.BytesIO(content), "text/plain")}
    upload = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    assert upload.status_code == 200, upload.text
    return upload.json()["document_version"]["version_id"]


def test_loader_qa_is_rejected_under_hard_cutover(client):
    project_id = _create_project(client)
    version_id = _upload_text_doc(client, project_id)
    resp = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "qa", "loader_params": {}},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_loader"


def test_loader_text_and_json_schema_are_supported(client):
    project_id = _create_project(client, "proj-loader-v022-2")
    version_id = _upload_text_doc(client, project_id, b'{"items":[{"a":1},{"a":2}]}')

    text_resp = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "text", "loader_params": {}},
    )
    assert text_resp.status_code == 200, text_resp.text
    assert text_resp.json()["segment_set"]["segment_set_version_id"]

    json_resp = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "json", "loader_params": {"schema": ".items", "schema_dialect": "dot_path", "output_format": "markdown"}},
    )
    assert json_resp.status_code == 200, json_resp.text
    assert len(json_resp.json()["items"]) >= 1

