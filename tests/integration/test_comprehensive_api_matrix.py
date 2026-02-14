import io
import json
from pathlib import Path

import pytest


def _create_project(client, name: str = "proj-main") -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "description": "desc", "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def _upload_document(client, project_id: str, filename: str = "sample.txt", content: bytes = b"hello") -> tuple[str, str]:
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    upload = client.post(
        f"/api/v1/projects/{project_id}/documents",
        data={"parser_params_json": '{"parser_type":"text"}'},
        files=files,
    )
    assert upload.status_code == 200, upload.text
    payload = upload.json()
    return payload["document"]["document_id"], payload["document_version"]["version_id"]


def _read_fixture_bytes(fixture_inputs_dir: Path, filename: str) -> bytes:
    return (fixture_inputs_dir / filename).read_bytes()


def _upload_fixture_document(
    client,
    project_id: str,
    fixture_inputs_dir: Path,
    filename: str,
    mime: str,
    parser_type: str = "text",
) -> tuple[str, str]:
    content = _read_fixture_bytes(fixture_inputs_dir, filename)
    files = {"file": (filename, io.BytesIO(content), mime)}
    upload = client.post(
        f"/api/v1/projects/{project_id}/documents",
        data={"parser_params_json": json.dumps({"parser_type": parser_type})},
        files=files,
    )
    assert upload.status_code == 200, upload.text
    payload = upload.json()
    return payload["document"]["document_id"], payload["document_version"]["version_id"]


def _create_segments(client, version_id: str, loader_type: str = "json", source_text: str = "A. B. C.") -> str:
    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": loader_type, "loader_params": {}, "source_text": source_text},
    )
    assert seg.status_code == 200, seg.text
    return seg.json()["segment_set"]["segment_set_version_id"]


def _create_chunks(client, segment_set_id: str, strategy: str = "regex", chunker_params: dict | None = None) -> str:
    chunk = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/chunk",
        json={"strategy": strategy, "chunker_params": chunker_params or {"pattern": "\\. "}},
    )
    assert chunk.status_code == 200, chunk.text
    return chunk.json()["chunk_set"]["chunk_set_version_id"]


def test_projects_documents_and_versions_crud_matrix(client, fixture_inputs_dir: Path):
    project_id = _create_project(client, "proj-crud")

    listed = client.get("/api/v1/projects")
    assert listed.status_code == 200
    assert any(p["project_id"] == project_id for p in listed.json())

    fetched = client.get(f"/api/v1/projects/{project_id}")
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == project_id

    patched = client.patch(f"/api/v1/projects/{project_id}", json={"name": "proj-crud-2", "settings": {"default_retrieval_preset": "x"}})
    assert patched.status_code == 200
    assert patched.json()["name"] == "proj-crud-2"

    document_id, version_id = _upload_document(
        client,
        project_id,
        filename="long_text.txt",
        content=_read_fixture_bytes(fixture_inputs_dir, "long_text.txt"),
    )

    docs = client.get(f"/api/v1/projects/{project_id}/documents")
    assert docs.status_code == 200
    assert any(d["document_id"] == document_id for d in docs.json())

    doc = client.get(f"/api/v1/documents/{document_id}")
    assert doc.status_code == 200
    assert doc.json()["document_id"] == document_id

    versions = client.get(f"/api/v1/documents/{document_id}/versions")
    assert versions.status_code == 200
    assert any(v["version_id"] == version_id for v in versions.json())


@pytest.mark.parametrize("loader_type", ["pdf", "docx", "csv", "excel", "json", "qa", "table"])
def test_segment_loader_type_matrix_with_source_text(client, loader_type: str):
    project_id = _create_project(client, f"proj-loader-{loader_type}")
    _, version_id = _upload_document(client, project_id, content=b"irrelevant")

    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": loader_type, "loader_params": {}, "source_text": f"source text for {loader_type}"},
    )
    assert seg.status_code == 200, seg.text
    payload = seg.json()
    assert payload["segment_set"]["segment_set_version_id"]
    assert len(payload["items"]) == 1


@pytest.mark.parametrize(
    "loader_type,filename,mime,loader_params,min_items",
    [
        ("docx", "long_document.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", {}, 1),
        ("csv", "long_data.csv", "text/csv", {"chunk_size": 40}, 5),
        ("excel", "long_workbook.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", {}, 3),
        ("json", "long_data.json", "application/json", {"jq_schema": ".items"}, 50),
        ("qa", "long_qa.txt", "text/plain", {}, 50),
        ("table", "long_table.csv", "text/csv", {"mode": "row"}, 100),
        ("table", "long_table.csv", "text/csv", {"mode": "group", "group_by": "region"}, 4),
    ],
)
def test_segment_loader_type_matrix_with_real_files(
    client,
    fixture_inputs_dir: Path,
    loader_type: str,
    filename: str,
    mime: str,
    loader_params: dict,
    min_items: int,
):
    project_id = _create_project(client, f"proj-loader-real-{loader_type}")
    _, version_id = _upload_fixture_document(client, project_id, fixture_inputs_dir, filename, mime, parser_type=loader_type)

    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": loader_type, "loader_params": loader_params},
    )
    assert seg.status_code == 200, seg.text
    payload = seg.json()
    assert payload["segment_set"]["segment_set_version_id"]
    assert len(payload["items"]) >= min_items


def test_segment_loader_invalid_type_errors_when_no_source_text(client):
    project_id = _create_project(client, "proj-invalid-loader")
    _, version_id = _upload_document(client, project_id, content=b"not json")

    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "invalid-loader", "loader_params": {}},
    )
    assert seg.status_code == 400


@pytest.mark.parametrize(
    "strategy,chunker_params",
    [
        ("recursive", {"chunk_size": 8, "chunk_overlap": 0}),
        ("regex", {"pattern": " "}),
        ("markdown_table", {}),
        ("token", {"chunk_size": 16, "chunk_overlap": 0, "model_name": "cl100k_base"}),
    ],
)
def test_chunk_strategy_matrix_for_core_strategies(client, strategy: str, chunker_params: dict):
    project_id = _create_project(client, f"proj-chunk-{strategy}")
    _, version_id = _upload_document(client, project_id)
    seg_set_id = _create_segments(client, version_id, source_text="| h | h2 |\n|---|---|\n|a|b|\nand text")

    chunk = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": strategy, "chunker_params": chunker_params},
    )
    assert chunk.status_code == 200, chunk.text
    assert chunk.json()["chunk_set"]["chunk_set_version_id"]
    assert len(chunk.json()["items"]) >= 1


def test_chunk_sentence_and_semantic_strategies_with_builder_patch(client, monkeypatch):
    class DummyChunker:
        def split_text(self, text: str):
            return [text[: max(1, len(text) // 2)], text[max(1, len(text) // 2) :]]

    from app.services import chunk_service as chunk_service_module

    original_build = chunk_service_module.ChunkService._build_chunker

    def patched_build(self, strategy: str, params: dict):
        if strategy in {"sentence", "semantic"}:
            return DummyChunker()
        return original_build(self, strategy, params)

    monkeypatch.setattr(chunk_service_module.ChunkService, "_build_chunker", patched_build)

    project_id = _create_project(client, "proj-sentence-semantic")
    _, version_id = _upload_document(client, project_id)
    seg_set_id = _create_segments(client, version_id, source_text="one two three four five")

    sentence = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": "sentence", "chunker_params": {"language": "english"}},
    )
    assert sentence.status_code == 200, sentence.text
    assert len(sentence.json()["items"]) == 2

    semantic = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": "semantic", "chunker_params": {"threshold": 0.5}},
    )
    assert semantic.status_code == 200, semantic.text
    assert len(semantic.json()["items"]) == 2


def test_chunk_invalid_strategy_returns_400(client):
    project_id = _create_project(client, "proj-chunk-invalid")
    _, version_id = _upload_document(client, project_id)
    seg_set_id = _create_segments(client, version_id)

    chunk = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": "invalid-strategy", "chunker_params": {}},
    )
    assert chunk.status_code == 400


def test_artifacts_pagination_soft_delete_restore(client):
    project_id = _create_project(client, "proj-artifacts")
    _, version_id = _upload_document(client, project_id)
    seg_set_id = _create_segments(client, version_id, source_text="alpha beta gamma")
    _ = _create_chunks(client, seg_set_id)

    page1 = client.get(f"/api/v1/projects/{project_id}/artifacts?limit=1")
    assert page1.status_code == 200, page1.text
    p1 = page1.json()
    assert len(p1["items"]) == 1
    assert p1["has_more"] is True
    assert p1["next_cursor"]

    page2 = client.get(f"/api/v1/projects/{project_id}/artifacts?limit=1&cursor={p1['next_cursor']}")
    assert page2.status_code == 200, page2.text
    assert len(page2.json()["items"]) == 1

    target_id = p1["items"][0]["artifact_id"]
    deleted = client.request("DELETE", f"/api/v1/artifacts/{target_id}", json={"reason": "test-delete"})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["ok"] is True

    restored = client.post(f"/api/v1/artifacts/{target_id}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["ok"] is True


def test_segment_and_chunk_clone_patch_versioning_and_active_flags(client):
    project_id = _create_project(client, "proj-clone-lineage")
    _, version_id = _upload_document(client, project_id, content=b"base")
    original_seg_set_id = _create_segments(client, version_id, source_text="alpha beta gamma")

    seg_before = client.get(f"/api/v1/segment_sets/{original_seg_set_id}")
    assert seg_before.status_code == 200, seg_before.text
    seg_item_id = seg_before.json()["items"][0]["item_id"]

    seg_patch = client.post(
        f"/api/v1/segment_sets/{original_seg_set_id}/clone_patch_item",
        json={
            "item_id": seg_item_id,
            "patch": {"content": "patched-segment", "metadata": {"edited": True}},
            "params": {"reason": "test-clone"},
        },
    )
    assert seg_patch.status_code == 200, seg_patch.text
    seg_patch_payload = seg_patch.json()
    patched_seg_set_id = seg_patch_payload["segment_set"]["segment_set_version_id"]

    assert patched_seg_set_id != original_seg_set_id
    assert seg_patch_payload["segment_set"]["parent_segment_set_version_id"] == original_seg_set_id
    assert seg_patch_payload["segment_set"]["input_refs"]["patched_item_id"] == seg_item_id
    assert seg_patch_payload["segment_set"]["params"]["clone_patch"] == {"reason": "test-clone"}
    assert seg_patch_payload["items"][0]["content"] == "patched-segment"
    assert seg_patch_payload["items"][0]["metadata"]["edited"] is True

    seg_after = client.get(f"/api/v1/segment_sets/{original_seg_set_id}")
    assert seg_after.status_code == 200, seg_after.text
    assert seg_after.json()["items"][0]["content"] == "alpha beta gamma"

    seg_list = client.get(f"/api/v1/projects/{project_id}/segment_sets")
    assert seg_list.status_code == 200, seg_list.text
    seg_by_id = {x["segment_set_version_id"]: x for x in seg_list.json()}
    assert seg_by_id[original_seg_set_id]["is_active"] is False
    assert seg_by_id[patched_seg_set_id]["is_active"] is True

    original_chunk_set_id = _create_chunks(client, patched_seg_set_id, strategy="regex", chunker_params={"pattern": " "})
    chunk_before = client.get(f"/api/v1/chunk_sets/{original_chunk_set_id}")
    assert chunk_before.status_code == 200, chunk_before.text
    chunk_item_id = chunk_before.json()["items"][0]["item_id"]

    chunk_patch = client.post(
        f"/api/v1/chunk_sets/{original_chunk_set_id}/clone_patch_item",
        json={
            "item_id": chunk_item_id,
            "patch": {"content": "patched-chunk", "metadata": {"edited": True}},
            "params": {"reason": "test-clone"},
        },
    )
    assert chunk_patch.status_code == 200, chunk_patch.text
    chunk_patch_payload = chunk_patch.json()
    patched_chunk_set_id = chunk_patch_payload["chunk_set"]["chunk_set_version_id"]

    assert patched_chunk_set_id != original_chunk_set_id
    assert chunk_patch_payload["chunk_set"]["parent_chunk_set_version_id"] == original_chunk_set_id
    assert chunk_patch_payload["chunk_set"]["input_refs"]["patched_item_id"] == chunk_item_id
    assert chunk_patch_payload["chunk_set"]["params"]["clone_patch"] == {"reason": "test-clone"}
    assert any(item["content"] == "patched-chunk" for item in chunk_patch_payload["items"])

    chunk_list = client.get(f"/api/v1/projects/{project_id}/chunk_sets")
    assert chunk_list.status_code == 200, chunk_list.text
    chunk_by_id = {x["chunk_set_version_id"]: x for x in chunk_list.json()}
    assert chunk_by_id[original_chunk_set_id]["is_active"] is False
    assert chunk_by_id[patched_chunk_set_id]["is_active"] is True


def test_parameter_persistence_for_generation_and_retrieval_chain(client, fixture_inputs_dir: Path):
    project_id = _create_project(client, "proj-params")
    parser_params = {"parser_type": "text", "trim": True, "hints": {"lang": "en"}}
    files = {"file": ("long_text.txt", io.BytesIO(_read_fixture_bytes(fixture_inputs_dir, "long_text.txt")), "text/plain")}
    upload = client.post(
        f"/api/v1/projects/{project_id}/documents",
        data={"parser_params_json": json.dumps(parser_params)},
        files=files,
    )
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["document"]["document_id"]
    version_id = upload.json()["document_version"]["version_id"]

    versions = client.get(f"/api/v1/documents/{document_id}/versions")
    assert versions.status_code == 200, versions.text
    version = next(v for v in versions.json() if v["version_id"] == version_id)
    assert version["parser_params"] == parser_params

    loader_params = {"jq_schema": ".items[]", "custom": {"x": 1}}
    seg = client.post(
        f"/api/v1/document_versions/{version_id}/segments",
        json={"loader_type": "json", "loader_params": loader_params, "source_text": _read_fixture_bytes(fixture_inputs_dir, "long_text.txt").decode("utf-8")},
    )
    assert seg.status_code == 200, seg.text
    seg_payload = seg.json()
    seg_set_id = seg_payload["segment_set"]["segment_set_version_id"]
    assert seg_payload["segment_set"]["params"]["loader_type"] == "json"
    assert seg_payload["segment_set"]["params"]["loader_params"] == loader_params
    assert seg_payload["segment_set"]["input_refs"]["document_version_id"] == version_id

    chunker_params = {"pattern": " ", "chunk_size": 32, "chunk_overlap": 0}
    chunk = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/chunk",
        json={"strategy": "regex", "chunker_params": chunker_params},
    )
    assert chunk.status_code == 200, chunk.text
    chunk_payload = chunk.json()
    chunk_set_id = chunk_payload["chunk_set"]["chunk_set_version_id"]
    assert chunk_payload["chunk_set"]["params"]["strategy"] == "regex"
    assert chunk_payload["chunk_set"]["params"]["chunker_params"] == chunker_params
    assert chunk_payload["chunk_set"]["input_refs"]["segment_set_version_id"] == seg_set_id

    index_req = {
        "name": "idx-params",
        "provider": "faiss",
        "index_type": "chunk_vectors",
        "config": {"embedding_provider": "mock"},
        "params": {"distance": "cosine", "build_tag": "v1"},
    }
    idx = client.post(f"/api/v1/projects/{project_id}/indexes", json=index_req)
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]
    assert idx.json()["config"] == index_req["config"]
    assert idx.json()["params"] == index_req["params"]

    build_params = {"batch_size": 2, "label": "param-check"}
    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": chunk_set_id, "params": build_params, "execution_mode": "sync"},
    )
    assert build.status_code == 200, build.text
    build_payload = build.json()["build"]
    assert build_payload["status"] == "succeeded"
    assert build_payload["params"] == build_params
    assert build_payload["input_refs"]["chunk_set_version_id"] == chunk_set_id

    ret = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": chunk_set_id,
            "persist": True,
            "strategy": {"type": "regex", "pattern": "alpha"},
            "limit": 3,
        },
    )
    assert ret.status_code == 200, ret.text
    run_id = ret.json()["run_id"]
    assert run_id

    run = client.get(f"/api/v1/retrieval_runs/{run_id}")
    assert run.status_code == 200, run.text
    run_payload = run.json()
    assert run_payload["strategy"] == "regex"
    assert run_payload["query"] == "alpha"
    assert run_payload["target_type"] == "chunk_set"
    assert run_payload["target_id"] == chunk_set_id
    assert run_payload["params"]["strategy"]["type"] == "regex"
    assert run_payload["params"]["strategy"]["pattern"] == "alpha"
    assert run_payload["params"]["limit"] == 3


def test_clone_patch_returns_404_for_unknown_item_id(client):
    project_id = _create_project(client, "proj-patch-404")
    _, version_id = _upload_document(client, project_id, content=b"alpha beta")
    seg_set_id = _create_segments(client, version_id, source_text="alpha beta gamma")
    chunk_set_id = _create_chunks(client, seg_set_id, strategy="regex", chunker_params={"pattern": " "})

    seg_patch = client.post(
        f"/api/v1/segment_sets/{seg_set_id}/clone_patch_item",
        json={"item_id": "missing-segment-item", "patch": {"content": "x"}, "params": {}},
    )
    assert seg_patch.status_code == 404

    chunk_patch = client.post(
        f"/api/v1/chunk_sets/{chunk_set_id}/clone_patch_item",
        json={"item_id": "missing-chunk-item", "patch": {"content": "x"}, "params": {}},
    )
    assert chunk_patch.status_code == 404


def test_artifact_soft_delete_restore_matrix_for_all_artifact_kinds(client):
    project_id = _create_project(client, "proj-delete-matrix")
    document_id, version_id = _upload_document(client, project_id, content=b"alpha beta")
    seg_set_id = _create_segments(client, version_id, source_text="alpha beta gamma")
    chunk_set_id = _create_chunks(client, seg_set_id, strategy="regex", chunker_params={"pattern": " "})

    idx = client.post(
        f"/api/v1/projects/{project_id}/indexes",
        json={"name": "idx-delete", "provider": "faiss", "index_type": "chunk_vectors", "config": {}, "params": {}},
    )
    assert idx.status_code == 200, idx.text
    index_id = idx.json()["index_id"]

    build = client.post(
        f"/api/v1/indexes/{index_id}/builds",
        json={"chunk_set_version_id": chunk_set_id, "params": {}, "execution_mode": "sync"},
    )
    assert build.status_code == 200, build.text
    build_id = build.json()["build"]["build_id"]

    ret = client.post(
        f"/api/v1/projects/{project_id}/retrieve",
        json={
            "query": "alpha",
            "target": "chunk_set",
            "target_id": chunk_set_id,
            "persist": True,
            "strategy": {"type": "regex", "pattern": "alpha"},
        },
    )
    assert ret.status_code == 200, ret.text
    run_id = ret.json()["run_id"]
    assert run_id

    for artifact_id in [document_id, version_id, seg_set_id, chunk_set_id, index_id, build_id, run_id]:
        deleted = client.request("DELETE", f"/api/v1/artifacts/{artifact_id}", json={"reason": "matrix"})
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["ok"] is True

        restored = client.post(f"/api/v1/artifacts/{artifact_id}/restore")
        assert restored.status_code == 200, restored.text
        assert restored.json()["ok"] is True
