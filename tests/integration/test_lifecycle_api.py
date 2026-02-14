import io
from pathlib import Path


def test_project_document_segment_chunk_lifecycle(client, fixture_inputs_dir: Path):
    # Create project
    resp = client.post(
        "/api/v1/projects",
        json={"name": "proj-a", "description": "test", "settings": {"default_chunking_preset": "x"}},
    )
    assert resp.status_code == 200, resp.text
    project_id = resp.json()["project_id"]

    # Upload document
    files = {"file": ("long_text.txt", io.BytesIO((fixture_inputs_dir / "long_text.txt").read_bytes()), "text/plain")}
    upload = client.post(
        f"/api/v1/projects/{project_id}/documents",
        data={"parser_params_json": "{}"},
        files=files,
    )
    assert upload.status_code == 200, upload.text
    version_id = upload.json()["document_version"]["version_id"]

    # Create segment set from source_text (deterministic)
    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={
            "loader_type": "json",
            "loader_params": {},
            "source_text": (fixture_inputs_dir / "long_text.txt").read_text(encoding="utf-8"),
        },
    )
    assert seg.status_code == 200, seg.text
    seg_set_id = seg.json()["segment_set"]["segment_set_version_id"]
    assert len(seg.json()["items"]) == 1

    # Chunk with regex splitter
    chunk = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": "regex", "chunker_params": {"pattern": "\\. "}},
    )
    assert chunk.status_code == 200, chunk.text
    chunk_set_id = chunk.json()["chunk_set"]["chunk_set_version_id"]
    assert len(chunk.json()["items"]) >= 1

    # Clone + patch one segment item
    first_seg_item = seg.json()["items"][0]["item_id"]
    seg_patch = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/clone_patch_item",
        json={"item_id": first_seg_item, "patch": {"content": "patched content"}, "params": {}},
    )
    assert seg_patch.status_code == 200, seg_patch.text
    assert seg_patch.json()["items"][0]["content"] == "patched content"

    # Clone + patch one chunk item
    first_chunk_item = chunk.json()["items"][0]["item_id"]
    chunk_patch = client.post(
        f"/api/v1/chunk_sets/{chunk_set_id}/clone_patch_item",
        json={"item_id": first_chunk_item, "patch": {"content": "patched chunk"}, "params": {}},
    )
    assert chunk_patch.status_code == 200, chunk_patch.text
    assert any(i["content"] == "patched chunk" for i in chunk_patch.json()["items"])

    # Artifacts list with cursor
    artifacts = client.get(f"/api/v1/projects/{project_id}/artifacts?limit=2")
    assert artifacts.status_code == 200, artifacts.text
    data = artifacts.json()
    assert "items" in data
    assert len(data["items"]) <= 2


def test_retrieval_and_optional_persistence(client, fixture_inputs_dir: Path):
    proj = client.post("/api/v1/projects", json={"name": "proj-r", "settings": {}})
    assert proj.status_code == 200
    project_id = proj.json()["project_id"]

    files = {"file": ("long_text.txt", io.BytesIO((fixture_inputs_dir / "long_text.txt").read_bytes()), "text/plain")}
    up = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    version_id = up.json()["document_version"]["version_id"]

    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "json", "loader_params": {}, "source_text": (fixture_inputs_dir / "long_text.txt").read_text(encoding="utf-8")},
    )
    seg_set_id = seg.json()["segment_set"]["segment_set_version_id"]

    chunk = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": "regex", "chunker_params": {"pattern": "\\. "}},
    )
    chunk_set_id = chunk.json()["chunk_set"]["chunk_set_version_id"]

    # bm25 no persistence
    ret = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "Section",
            "target": "chunk_set",
            "target_id": chunk_set_id,
            "persist": False,
            "strategy": {"type": "bm25", "k": 5},
        },
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["run_id"] is None
    assert ret.json()["total"] >= 1

    # regex with persistence
    ret2 = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "Section",
            "target": "chunk_set",
            "target_id": chunk_set_id,
            "persist": True,
            "strategy": {"type": "regex", "pattern": "Section"},
        },
    )
    assert ret2.status_code == 200, ret2.text
    run_id = ret2.json()["run_id"]
    assert run_id

    runs = client.get(f"/api/v1/projects/{project_id}/retrieval_runs")
    assert runs.status_code == 200
    assert any(r["run_id"] == run_id for r in runs.json())

    delete = client.delete(f"/api/v1/retrieval_runs/{run_id}")
    assert delete.status_code == 200
    assert delete.json()["ok"] is True
