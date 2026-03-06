import sys
import types
from types import SimpleNamespace

import pytest


def _install_fake_celery(monkeypatch) -> None:
    class _DummyTask:
        def __init__(self, fn):
            self.run = fn

        def __call__(self, *args, **kwargs):
            return self.run(*args, **kwargs)

        def delay(self, *args, **kwargs):
            return None

    class _DummyConf:
        def update(self, **kwargs):
            return None

    class _DummyCelery:
        def __init__(self, *args, **kwargs):
            self.conf = _DummyConf()

        def task(self, name=None):
            def _decorate(fn):
                return _DummyTask(fn)

            return _decorate

    fake_celery_module = types.ModuleType("celery")
    fake_celery_module.Celery = _DummyCelery
    monkeypatch.setitem(sys.modules, "celery", fake_celery_module)
    sys.modules.pop("app.workers.celery_app", None)
    sys.modules.pop("app.workers.tasks", None)


@pytest.fixture(autouse=True)
def _fake_celery_runtime(monkeypatch):
    _install_fake_celery(monkeypatch)


def _create_project(client, name: str) -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def test_submit_url_load_enqueues_job(client, monkeypatch):
    project_id = _create_project(client, "url-load-submit-enqueue")
    delay_calls: list[tuple] = []

    def _delay(job_id, pid, loader_type, loader_params):
        delay_calls.append((job_id, pid, loader_type, loader_params))
        return None

    monkeypatch.setattr("app.workers.tasks.run_document_load_from_url.delay", _delay)

    resp = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url/submit",
        json={
            "loader_type": "web",
            "loader_params": {"url": "https://example.com", "fetch_mode": "playwright"},
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["mode"] == "async"
    assert payload["status"] == "queued"
    assert payload["job_id"]

    assert len(delay_calls) == 1
    assert delay_calls[0][1] == project_id
    assert delay_calls[0][2] == "web"
    assert delay_calls[0][3]["url"] == "https://example.com"

    job_resp = client.get(f"/api/v1/jobs/{payload['job_id']}")
    assert job_resp.status_code == 200, job_resp.text
    job = job_resp.json()
    assert job["job_type"] == "document_load_url"
    assert job["status"] == "queued"
    assert job["payload"]["project_id"] == project_id
    assert job["payload"]["loader_type"] == "web"
    assert job["payload"]["url"] == "https://example.com"
    assert job["payload"]["fetch_mode"] == "playwright"


def test_submit_url_load_job_worker_success(client, monkeypatch):
    project_id = _create_project(client, "url-load-submit-success")

    async def _load_from_url(self, *, project_id: str, loader_type: str | None, loader_params: dict | None):
        return SimpleNamespace(document_set_version_id="dsv-submit-success", project_id=project_id)

    monkeypatch.setattr("app.services.document_load_service.DocumentLoadService.load_from_url", _load_from_url)

    resp = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url/submit",
        json={
            "loader_type": "web_async",
            "loader_params": {"url": "https://example.com/async", "fetch_mode": "playwright"},
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    job_id = payload["job_id"]

    from app.workers.tasks import run_document_load_from_url

    run_document_load_from_url.run(
        job_id,
        project_id,
        "web_async",
        {"url": "https://example.com/async", "fetch_mode": "playwright"},
    )

    job_resp = client.get(f"/api/v1/jobs/{job_id}")
    assert job_resp.status_code == 200, job_resp.text
    job = job_resp.json()
    assert job["status"] == "succeeded"
    assert job["result"]["document_set_version_id"] == "dsv-submit-success"
    assert job["result"]["project_id"] == project_id
    assert job["result"]["total_items"] == 0
    assert job["result"]["status"] == "succeeded"


def test_submit_url_load_job_worker_failure(client, monkeypatch):
    project_id = _create_project(client, "url-load-submit-failure")

    async def _load_from_url(self, *, project_id: str, loader_type: str | None, loader_params: dict | None):
        raise RuntimeError("submit-worker-failure")

    monkeypatch.setattr("app.services.document_load_service.DocumentLoadService.load_from_url", _load_from_url)

    resp = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url/submit",
        json={
            "loader_type": "web",
            "loader_params": {"url": "https://example.com", "fetch_mode": "playwright"},
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    job_id = payload["job_id"]

    from app.workers.tasks import run_document_load_from_url

    try:
        run_document_load_from_url.run(
            job_id,
            project_id,
            "web",
            {"url": "https://example.com", "fetch_mode": "playwright"},
        )
    except Exception:
        pass

    job_resp = client.get(f"/api/v1/jobs/{job_id}")
    assert job_resp.status_code == 200, job_resp.text
    job = job_resp.json()
    assert job["status"] == "failed"
    assert "submit-worker-failure" in (job["error_message"] or "")


def test_submit_url_load_requires_url(client, monkeypatch):
    project_id = _create_project(client, "url-load-submit-missing-url")

    monkeypatch.setattr("app.workers.tasks.run_document_load_from_url.delay", lambda *args, **kwargs: None)

    resp = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url/submit",
        json={"loader_type": "web", "loader_params": {}},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["code"] == "invalid_loader_params"
