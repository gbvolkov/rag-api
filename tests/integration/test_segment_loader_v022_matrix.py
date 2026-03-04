import io


def _create_project(client, name: str = "proj-loader-v022") -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def _upload_doc(
    client,
    project_id: str,
    *,
    filename: str = "doc.txt",
    mime: str = "text/plain",
    content: bytes = b"alpha beta gamma",
) -> str:
    files = {"file": (filename, io.BytesIO(content), mime)}
    upload = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    assert upload.status_code == 200, upload.text
    return upload.json()["document_version"]["version_id"]


def test_loader_qa_is_rejected_under_hard_cutover(client):
    project_id = _create_project(client)
    version_id = _upload_doc(client, project_id)
    resp = client.post(
        f"/api/v1/document_versions/{version_id}/load_documents",
        json={"loader_type": "qa", "loader_params": {}},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_loader"


def test_loader_text_and_json_schema_are_supported(client):
    project_id = _create_project(client, "proj-loader-v022-2")
    version_id = _upload_doc(
        client,
        project_id,
        filename="doc.json",
        mime="application/json",
        content=b'{"items":[{"a":1},{"a":2}]}',
    )

    text_resp = client.post(
        f"/api/v1/document_versions/{version_id}/load_documents",
        json={"loader_type": "text", "loader_params": {}},
    )
    assert text_resp.status_code == 200, text_resp.text
    assert text_resp.json()["document_set"]["document_set_version_id"]

    json_resp = client.post(
        f"/api/v1/document_versions/{version_id}/load_documents",
        json={"loader_type": "json", "loader_params": {"schema": ".items", "schema_dialect": "dot_path", "output_format": "markdown"}},
    )
    assert json_resp.status_code == 200, json_resp.text
    assert len(json_resp.json()["items"]) >= 1


def test_removed_combined_endpoints_are_absent(client):
    project_id = _create_project(client, "proj-loader-v022-removed")
    version_id = _upload_doc(client, project_id)

    old_file_endpoint = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "text", "loader_params": {}},
    )
    assert old_file_endpoint.status_code == 404, old_file_endpoint.text

    old_url_endpoint = client.post(
        f"/api/v1/projects/{project_id}/segments/url",
        json={"loader_type": "web", "loader_params": {"url": "https://example.com"}},
    )
    assert old_url_endpoint.status_code == 404, old_url_endpoint.text


def test_loader_override_disallowed_by_policy_fails(client):
    project_id = _create_project(client, "proj-loader-v022-policy")
    version_id = _upload_doc(client, project_id, filename="doc.txt", mime="text/plain", content=b'{"a":1}')
    resp = client.post(
        f"/api/v1/document_versions/{version_id}/load_documents",
        json={"loader_type": "json", "loader_params": {"schema": "."}},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "loader_not_allowed_for_document_class"


def test_url_loader_cannot_be_used_for_file_document_versions(client):
    project_id = _create_project(client, "proj-loader-v022-source-kind")
    version_id = _upload_doc(client, project_id, filename="doc.txt", mime="text/plain", content=b"alpha")
    resp = client.post(
        f"/api/v1/document_versions/{version_id}/load_documents",
        json={"loader_type": "web", "loader_params": {"url": "https://example.com"}},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] in {
        "loader_not_allowed_for_document_class",
        "loader_not_allowed_for_source",
    }


def test_segment_creation_rejects_loader_fields(client):
    project_id = _create_project(client, "proj-loader-v022-segment-validation")
    version_id = _upload_doc(client, project_id)
    loaded = client.post(
        f"/api/v1/document_versions/{version_id}/load_documents",
        json={"loader_type": "text", "loader_params": {}},
    )
    assert loaded.status_code == 200, loaded.text
    document_set_id = loaded.json()["document_set"]["document_set_version_id"]

    resp = client.post(
        f"/api/v1/document_sets/{document_set_id}/segments",
        json={
            "split_strategy": "identity",
            "splitter_params": {},
            "params": {},
            "loader_type": "text",
        },
    )
    assert resp.status_code == 422, resp.text
