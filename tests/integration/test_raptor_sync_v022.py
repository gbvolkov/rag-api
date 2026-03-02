import io


def _create_project(client, name: str = "proj-raptor-v022") -> str:
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


def test_raptor_sync_persists_raptor_run(client, monkeypatch):
    from app.core.config import settings
    from app.services import segment_transform_service as sts

    monkeypatch.setattr(settings, "feature_enable_raptor", True)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    monkeypatch.setattr(sts, "require_module", lambda *args, **kwargs: None)
    monkeypatch.setattr(sts.SegmentTransformService, "_get_llm", lambda self, provider, model, temperature: object())

    class _DummyRaptorProcessor:
        def __init__(self, llm, embeddings, max_levels):
            self.max_levels = max_levels

        def process_segments(self, segments):
            return segments

    monkeypatch.setattr("rag_lib.processors.raptor.RaptorProcessor", _DummyRaptorProcessor)
    monkeypatch.setattr("rag_lib.embeddings.factory.create_embeddings_model", lambda provider, model_name: object())

    project_id = _create_project(client)
    segment_set_id = _create_segment_set(client, project_id)

    resp = client.post(
        f"/api/v1/segment_sets/{segment_set_id}/raptor",
        json={
            "execution_mode": "sync",
            "max_levels": 2,
            "embedding_provider": "mock",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["segment_set"]["segment_set_version_id"]

    runs = client.get(f"/api/v1/projects/{project_id}/raptor_runs")
    assert runs.status_code == 200, runs.text
    assert len(runs.json()) >= 1
