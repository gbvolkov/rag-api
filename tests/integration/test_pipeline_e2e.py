import io
import threading
from pathlib import Path


class _ImmediateTask:
    def __init__(self, fn):
        self._fn = fn

    def delay(self, *args, **kwargs):
        result: dict[str, object] = {}
        error: dict[str, BaseException] = {}

        def _run():
            try:
                result["value"] = self._fn(*args, **kwargs)
            except BaseException as exc:  # pragma: no cover - defensive for test harness thread
                error["exc"] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join()

        if "exc" in error:
            raise error["exc"]
        return result.get("value")


def _create_project(client, name: str) -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def _create_faiss_index(client, project_id: str, name: str = "faiss-main") -> str:
    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": name, "provider": "faiss", "index_type": "chunk_vectors", "config": {}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    return idx.json()["index_id"]


def _fixture_bytes(fixture_inputs_dir: Path, filename: str) -> bytes:
    return (fixture_inputs_dir / filename).read_bytes()


def _create_chunk_set_for_project(client, project_id: str, text: str = "alpha beta. gamma delta") -> str:
    files = {"file": ("doc.txt", io.BytesIO(b"x"), "text/plain")}
    upload = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    version_id = upload.json()["document_version"]["version_id"]

    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "json", "loader_params": {}, "source_text": text},
    )
    seg_set_id = seg.json()["segment_set"]["segment_set_version_id"]

    chunk = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": "regex", "chunker_params": {"pattern": "\\. "}},
    )
    assert chunk.status_code == 200, chunk.text
    return chunk.json()["chunk_set"]["chunk_set_version_id"]


def test_pipeline_sync_end_to_end_with_faiss_index_and_retrieval(client, fixture_inputs_dir: Path):
    project_id = _create_project(client, "proj-pipeline-sync")
    index_id = _create_faiss_index(client, project_id, "faiss-pipeline")

    files = {"file": ("long_qa.txt", io.BytesIO(_fixture_bytes(fixture_inputs_dir, "long_qa.txt")), "text/plain")}

    response = client.post(
        f"/api/v1/projects/{project_id}/pipeline/file",
        files=files,
        data={
            "loader_type": "qa",
            "loader_params_json": "{}",
            "chunk_strategy": "regex",
            "chunker_params_json": '{"pattern":"\\nQ: "}',
            "create_index": "true",
            "index_id": index_id,
            "index_params_json": "{}",
            "execution_mode": "sync",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["status"] == "succeeded"
    assert payload["document_id"]
    assert payload["document_version_id"]
    assert payload["segment_set_version_id"]
    assert payload["chunk_set_version_id"]
    assert payload["index_build_id"]

    retrieve = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": payload["index_build_id"],
            "persist": False,
            "strategy": {"type": "vector", "k": 5},
        },
    )
    assert retrieve.status_code == 200, retrieve.text
    assert retrieve.json()["total"] >= 1


def test_pipeline_sync_without_index_supports_unindexed_retrieval(client, fixture_inputs_dir: Path):
    project_id = _create_project(client, "proj-pipeline-sync-no-index")

    files = {"file": ("long_qa.txt", io.BytesIO(_fixture_bytes(fixture_inputs_dir, "long_qa.txt")), "text/plain")}

    response = client.post(
        f"/api/v1/projects/{project_id}/pipeline/file",
        files=files,
        data={
            "loader_type": "qa",
            "loader_params_json": "{}",
            "chunk_strategy": "regex",
            "chunker_params_json": '{"pattern":"\\nQ: "}',
            "create_index": "false",
            "execution_mode": "sync",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["status"] == "succeeded"
    assert payload["index_build_id"] is None
    assert payload["chunk_set_version_id"]

    retrieve = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "retrieval",
            "target": "chunk_set",
            "target_id": payload["chunk_set_version_id"],
            "persist": False,
            "strategy": {"type": "regex", "pattern": "retrieval"},
        },
    )
    assert retrieve.status_code == 200, retrieve.text
    assert retrieve.json()["total"] >= 1


def test_pipeline_async_end_to_end_job_visibility(client, monkeypatch, fixture_inputs_dir: Path):
    project_id = _create_project(client, "proj-pipeline-async")

    from app.workers import tasks as worker_tasks

    monkeypatch.setattr("app.api.api_v1.endpoints.pipeline.run_pipeline", _ImmediateTask(worker_tasks.run_pipeline))

    files = {"file": ("long_qa.txt", io.BytesIO(_fixture_bytes(fixture_inputs_dir, "long_qa.txt")), "text/plain")}

    response = client.post(
        f"/api/v1/projects/{project_id}/pipeline/file",
        files=files,
        data={
            "loader_type": "qa",
            "loader_params_json": "{}",
            "chunk_strategy": "regex",
            "chunker_params_json": '{"pattern":"\\nQ: "}',
            "create_index": "false",
            "execution_mode": "async",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["job_id"]

    job_id = payload["job_id"]
    # In the local fallback worker, delay() executes immediately; still tolerate transient states.
    job = client.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200, job.text
    assert job.json()["status"] == "succeeded"
    assert job.json()["result"]["document_id"]
    assert job.json()["result"]["segment_set_version_id"]
    assert job.json()["result"]["chunk_set_version_id"]

    project_jobs = client.get(f"/api/v1/projects/{project_id}/jobs")
    assert project_jobs.status_code == 200
    assert any(j["job_id"] == job_id for j in project_jobs.json())

    admin_jobs = client.get("/api/v1/admin/jobs")
    assert admin_jobs.status_code == 200
    assert any(j["job_id"] == job_id for j in admin_jobs.json())

    retrieve = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "retrieval",
            "target": "chunk_set",
            "target_id": job.json()["result"]["chunk_set_version_id"],
            "persist": False,
            "strategy": {"type": "regex", "pattern": "retrieval"},
        },
    )
    assert retrieve.status_code == 200, retrieve.text
    assert retrieve.json()["total"] >= 1


def test_index_build_async_job_flow_and_build_listing(client, monkeypatch):
    project_id = _create_project(client, "proj-index-async")
    chunk_set_id = _create_chunk_set_for_project(client, project_id)
    index_id = _create_faiss_index(client, project_id, "faiss-async")

    from app.workers import tasks as worker_tasks

    monkeypatch.setattr("app.api.api_v1.endpoints.indexes.run_index_build", _ImmediateTask(worker_tasks.run_index_build))

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": chunk_set_id, "params": {"label": "async-test"}, "execution_mode": "async"},
    )
    assert build.status_code == 200, build.text
    payload = build.json()
    assert payload["mode"] == "async"
    assert payload["job_id"]
    assert payload["build"]["build_id"]

    build_id = payload["build"]["build_id"]

    builds = client.get(f"/api/v1/indexes/{index_id}/builds")
    assert builds.status_code == 200, builds.text
    assert any(b["build_id"] == build_id for b in builds.json())

    fetched = client.get(f"/api/v1/index_builds/{build_id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["build_id"] == build_id

    job = client.get(f"/api/v1/jobs/{payload['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "succeeded"
    assert job.json()["result"]["build_id"] == build_id

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
    assert retrieve.json()["total"] >= 1
