import io
import types
import sys


def _create_project(client, name: str) -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def _upload_text_document(client, project_id: str, content: bytes) -> str:
    files = {"file": ("doc.txt", io.BytesIO(content), "text/plain")}
    resp = client.post(f"/api/v1/projects/{project_id}/documents", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()["document_version"]["version_id"]


def _create_segments(client, version_id: str) -> tuple[str, list[dict]]:
    loaded = client.post(
        f"/api/v1/document_versions/{version_id}/load_documents",
        json={"loader_type": "text", "loader_params": {}},
    )
    assert loaded.status_code == 200, loaded.text
    document_set_id = loaded.json()["document_set"]["document_set_version_id"]
    resp = client.post(
        f"/api/v1/document_sets/{document_set_id}/segments",
        json={"split_strategy": "identity", "splitter_params": {}, "params": {}},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    return payload["segment_set"]["segment_set_version_id"], payload["items"]


def _split_segment_set(client, segment_set_id: str, strategy: str, splitter_params: dict | None = None) -> dict:
    resp = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/split",
        json={"strategy": strategy, "splitter_params": splitter_params or {}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_index(client, project_id: str, name: str) -> str:
    resp = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={
            "name": name,
            "provider": "faiss",
            "index_type": "segment_vectors",
            "config": {"embedding_provider": "mock"},
            "params": {},
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["index_id"]


def _stub_worker_tasks(monkeypatch) -> None:
    class _DummyTask:
        @staticmethod
        def delay(*args, **kwargs):
            return None

    fake_tasks = types.ModuleType("app.workers.tasks")
    fake_tasks.run_pipeline = _DummyTask()
    fake_tasks.run_index_build = _DummyTask()
    fake_tasks.run_graph_build = _DummyTask()
    fake_tasks.run_segment_enrich = _DummyTask()
    fake_tasks.run_segment_raptor = _DummyTask()
    monkeypatch.setitem(sys.modules, "app.workers.tasks", fake_tasks)


def test_split_happy_path_and_chained_split(client):
    project_id = _create_project(client, "split-happy")
    version_id = _upload_text_document(client, project_id, b"alpha beta. gamma delta. epsilon zeta.")
    base_set_id, _ = _create_segments(client, version_id)

    parent = _split_segment_set(client, base_set_id, "regex", {"pattern": r"\.\s+"})
    parent_set_id = parent["segment_set"]["segment_set_version_id"]
    assert len(parent["items"]) >= 2

    child = _split_segment_set(client, parent_set_id, "recursive", {"chunk_size": 16, "chunk_overlap": 0})
    assert len(child["items"]) >= 2
    assert child["segment_set"]["parent_segment_set_version_id"] == parent_set_id


def test_split_validation_error_for_invalid_strategy(client):
    project_id = _create_project(client, "split-invalid")
    version_id = _upload_text_document(client, project_id, b"alpha beta")
    segment_set_id, _ = _create_segments(client, version_id)

    resp = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/split",
        json={"strategy": "not-a-strategy", "splitter_params": {}},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "unsupported_split_strategy"


def test_index_build_vector_only_with_source_set_id(client):
    project_id = _create_project(client, "index-vector-only")
    version_id = _upload_text_document(client, project_id, b"alpha beta gamma delta")
    source_set_id, _ = _create_segments(client, version_id)
    index_id = _create_index(client, project_id, "idx-vector-only")

    resp = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"source_set_id": source_set_id, "params": {}, "execution_mode": "sync"},
    )
    assert resp.status_code == 200, resp.text
    build = resp.json()["build"]
    assert build["source_set_id"] == source_set_id
    assert build["status"] == "succeeded"


def test_index_build_dual_storage_with_explicit_source_and_parent(client):
    project_id = _create_project(client, "index-dual-storage")
    version_id = _upload_text_document(client, project_id, b"alpha beta gamma. delta epsilon zeta.")
    parent_set_id, _ = _create_segments(client, version_id)
    source = _split_segment_set(client, parent_set_id, "recursive", {"chunk_size": 14, "chunk_overlap": 0})
    source_set_id = source["segment_set"]["segment_set_version_id"]
    index_id = _create_index(client, project_id, "idx-dual-storage")

    resp = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={
            "source_set_id": source_set_id,
            "parent_set_id": parent_set_id,
            "id_key": "source_segment_item_id",
            "doc_store": {"backend": "local_file"},
            "params": {},
            "execution_mode": "sync",
        },
    )
    assert resp.status_code == 200, resp.text
    build = resp.json()["build"]
    assert build["source_set_id"] == source_set_id
    assert build["parent_set_id"] == parent_set_id
    assert build["doc_store"]["backend"] == "local_file"


def test_dual_storage_build_missing_id_key_and_unresolved_parent_ids_fail(client):
    project_id = _create_project(client, "index-dual-failures")
    version_id = _upload_text_document(client, project_id, b"alpha beta gamma. delta epsilon zeta.")
    parent_set_id, _ = _create_segments(client, version_id)
    source = _split_segment_set(client, parent_set_id, "recursive", {"chunk_size": 14, "chunk_overlap": 0})
    source_set_id = source["segment_set"]["segment_set_version_id"]
    index_id = _create_index(client, project_id, "idx-dual-failures")

    missing_key_resp = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={
            "source_set_id": source_set_id,
            "parent_set_id": parent_set_id,
            "id_key": "missing_id_key",
            "doc_store": {"backend": "local_file"},
            "params": {},
            "execution_mode": "sync",
        },
    )
    assert missing_key_resp.status_code == 400, missing_key_resp.text
    assert missing_key_resp.json()["detail"]["code"] == "doc_store_parent_key_missing"

    items = source["items"]
    patch_resp = client.post(
        f"/api/v1/segment_sets/{source_set_id}/clone_patch_item",
        json={
            "item_id": items[0]["item_id"],
            "patch": {"metadata": {"source_segment_item_id": "missing-parent-id"}},
            "params": {},
        },
    )
    assert patch_resp.status_code == 200, patch_resp.text
    patched_source_set_id = patch_resp.json()["segment_set"]["segment_set_version_id"]

    unresolved_resp = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={
            "source_set_id": patched_source_set_id,
            "parent_set_id": parent_set_id,
            "id_key": "source_segment_item_id",
            "doc_store": {"backend": "local_file"},
            "params": {},
            "execution_mode": "sync",
        },
    )
    assert unresolved_resp.status_code == 400, unresolved_resp.text
    assert unresolved_resp.json()["detail"]["code"] == "doc_store_parent_not_found"


def test_dual_storage_retrieval_rejects_id_key_mismatch(client):
    project_id = _create_project(client, "dual-storage-id-key-mismatch")
    version_id = _upload_text_document(client, project_id, b"alpha beta gamma. delta epsilon zeta.")
    parent_set_id, _ = _create_segments(client, version_id)
    source = _split_segment_set(client, parent_set_id, "recursive", {"chunk_size": 14, "chunk_overlap": 0})
    source_set_id = source["segment_set"]["segment_set_version_id"]
    index_id = _create_index(client, project_id, "idx-dual-mismatch")

    build_resp = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={
            "source_set_id": source_set_id,
            "parent_set_id": parent_set_id,
            "id_key": "source_segment_item_id",
            "doc_store": {"backend": "local_file"},
            "params": {},
            "execution_mode": "sync",
        },
    )
    assert build_resp.status_code == 200, build_resp.text
    build_id = build_resp.json()["build"]["build_id"]

    retrieve_resp = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "alpha",
            "target": "index_build",
            "target_id": build_id,
            "strategy": {
                "type": "dual_storage",
                "vector_search": {"k": 2},
                "search_kwargs": {"k": 2},
                "id_key": "wrong_key",
            },
        },
    )
    assert retrieve_resp.status_code == 400, retrieve_resp.text
    assert retrieve_resp.json()["detail"]["code"] == "dual_storage_id_key_mismatch"


def test_retrieval_rejects_target_chunk_set(client):
    project_id = _create_project(client, "retrieve-target-chunk-set")
    resp = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": "dummy",
            "strategy": {"type": "bm25", "k": 1},
        },
    )
    assert resp.status_code == 422, resp.text


def test_graph_rejects_source_type_chunk_set(client):
    project_id = _create_project(client, "graph-source-type-chunk-set")
    resp = client.post(
        f"/api/v1/projects/{project_id}/graph/builds",
        json={
            "source_type": "chunk_set",
            "source_id": "dummy",
            "backend": "networkx",
            "execution_mode": "sync",
        },
    )
    assert resp.status_code == 422, resp.text


def test_pipeline_sync_and_async_outputs_are_segment_only(client, monkeypatch):
    _stub_worker_tasks(monkeypatch)
    project_id = _create_project(client, "pipeline-segment-only")
    payload = b"alpha beta gamma. delta epsilon zeta."

    sync_resp = client.post(
        f"/api/v1/projects/{project_id}/pipeline/file",
        files={"file": ("doc.txt", io.BytesIO(payload), "text/plain")},
        data={
            "loader_type": "text",
            "split_strategy": "recursive",
            "splitter_params_json": '{"chunk_size": 20, "chunk_overlap": 0}',
            "create_index": "false",
            "execution_mode": "sync",
        },
    )
    assert sync_resp.status_code == 200, sync_resp.text
    sync_payload = sync_resp.json()
    assert sync_payload["document_set_version_id"]
    assert sync_payload["segment_set_version_id"]
    assert "source_set_id" not in sync_payload

    async_resp = client.post(
        f"/api/v1/projects/{project_id}/pipeline/file",
        files={"file": ("doc.txt", io.BytesIO(payload), "text/plain")},
        data={
            "loader_type": "text",
            "split_strategy": "recursive",
            "splitter_params_json": '{"chunk_size": 20, "chunk_overlap": 0}',
            "create_index": "false",
            "execution_mode": "async",
        },
    )
    assert async_resp.status_code == 200, async_resp.text
    async_payload = async_resp.json()
    assert async_payload["job_id"]
    assert async_payload["document_set_version_id"] is None
    assert "source_set_id" not in async_payload


def test_artifacts_listing_excludes_chunk_artifact_kinds(client):
    project_id = _create_project(client, "artifact-kind-segment-only")
    version_id = _upload_text_document(client, project_id, b"alpha beta")
    _create_segments(client, version_id)

    resp = client.get(f"/api/v1/projects/{project_id}/artifacts")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    kinds = {item["artifact_kind"] for item in items}
    assert "chunk_set" not in kinds
    assert "chunk_item" not in kinds
    assert "segment_set" in kinds


def test_doc_store_redis_requires_strict_fields_and_accepts_explicit_config(client, monkeypatch):
    _stub_worker_tasks(monkeypatch)
    project_id = _create_project(client, "redis-doc-store-validation")
    version_id = _upload_text_document(client, project_id, b"alpha beta gamma")
    parent_set_id, _ = _create_segments(client, version_id)
    source = _split_segment_set(client, parent_set_id, "recursive", {"chunk_size": 12, "chunk_overlap": 0})
    source_set_id = source["segment_set"]["segment_set_version_id"]
    index_id = _create_index(client, project_id, "idx-redis-doc-store")

    invalid_resp = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={
            "source_set_id": source_set_id,
            "parent_set_id": parent_set_id,
            "id_key": "source_segment_item_id",
            "doc_store": {"backend": "redis", "redis_url": "redis://localhost:6379/0"},
            "params": {},
            "execution_mode": "sync",
        },
    )
    assert invalid_resp.status_code == 422, invalid_resp.text

    accepted_resp = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={
            "source_set_id": source_set_id,
            "parent_set_id": parent_set_id,
            "id_key": "source_segment_item_id",
            "doc_store": {
                "backend": "redis",
                "redis_url": "redis://localhost:6379/0",
                "redis_namespace": "seg-only-tests",
                "redis_ttl": 3600,
            },
            "params": {},
            "execution_mode": "async",
        },
    )
    assert accepted_resp.status_code == 200, accepted_resp.text
    assert accepted_resp.json()["mode"] == "async"
