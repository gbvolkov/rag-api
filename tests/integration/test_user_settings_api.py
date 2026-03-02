def _create_project(client, name: str = "proj-user-settings") -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def test_user_settings_resolution_with_project_override(client):
    project_id = _create_project(client)

    user = client.post("/api/v1/users", json={"external_subject": "ext-1", "profile": {"name": "A"}})
    assert user.status_code == 200, user.text
    user_id = user.json()["user_id"]

    global_settings = client.put(
        f"/api/v1/users/{user_id}/settings",
        json={"settings": {"retrieval_top_k": 5, "chunk_strategy": "recursive"}},
    )
    assert global_settings.status_code == 200, global_settings.text

    project_settings = client.put(
        f"/api/v1/projects/{project_id}/users/{user_id}/settings",
        json={"settings": {"retrieval_top_k": 10}},
    )
    assert project_settings.status_code == 200, project_settings.text
    resolved = project_settings.json()["resolved_settings"]
    assert resolved["retrieval_top_k"] == 10
    assert resolved["chunk_strategy"] == "recursive"

