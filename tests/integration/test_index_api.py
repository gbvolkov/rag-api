import io
from pathlib import Path


def test_faiss_provider_build_and_retrieve(client, fixture_inputs_dir: Path):
    proj = client.post("/api/v1/projects", json={"name": "proj-faiss", "settings": {}})
    project_id = proj.json()["project_id"]

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={
            "name": "faiss-index",
            "provider": "faiss",
            "index_type": "chunk_vectors",
            "config": {},
            "params": {},
        },
    )
    assert idx.status_code == 200
    index_id = idx.json()["index_id"]

    files = {"file": ("long_text.txt", io.BytesIO((fixture_inputs_dir / "long_text.txt").read_bytes()), "text/plain")}
    up = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    version_id = up.json()["document_version"]["version_id"]
    source_text = (fixture_inputs_dir / "long_text.txt").read_text(encoding="utf-8")
    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "json", "loader_params": {}, "source_text": source_text},
    )
    seg_id = seg.json()["segment_set"]["segment_set_version_id"]
    chunk = client.post(
        f"/api/v1/segment_sets/{seg_id}/chunk",
        json={"strategy": "regex", "chunker_params": {"pattern": " "}},
    )
    chunk_id = chunk.json()["chunk_set"]["chunk_set_version_id"]

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": chunk_id, "params": {}, "execution_mode": "sync"},
    )
    assert build.status_code == 200, build.text
    build_payload = build.json()["build"]
    assert build_payload["status"] == "succeeded"
    build_id = build_payload["build_id"]

    retrieve = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "persist": False,
            "strategy": {"type": "vector", "k": 3},
        },
    )
    assert retrieve.status_code == 200, retrieve.text
    data = retrieve.json()
    assert data["total"] >= 1
