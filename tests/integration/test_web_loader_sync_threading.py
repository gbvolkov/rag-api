import asyncio

from langchain_core.documents import Document as LCDocument


def _create_project(client, name: str) -> str:
    resp = client.post("/api/v1/projects", json={"name": name, "settings": {}})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_id"]


def test_sync_web_loader_runs_outside_request_event_loop(client, monkeypatch):
    project_id = _create_project(client, "web-sync-threading")
    observed = {"inside_event_loop": None}

    def _load(_self):
        try:
            asyncio.get_running_loop()
            observed["inside_event_loop"] = True
        except RuntimeError:
            observed["inside_event_loop"] = False
        return [LCDocument(page_content="sync web content", metadata={"source": "https://example.com"})]

    monkeypatch.setattr("rag_lib.loaders.web.WebLoader.load", _load)

    response = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url",
        json={
            "loader_type": "web",
            "loader_params": {"url": "https://example.com", "depth": 0, "fetch_mode": "playwright"},
        },
    )
    assert response.status_code == 200, response.text
    assert observed["inside_event_loop"] is False


def test_sync_web_loader_forces_playwright_headless(client, monkeypatch):
    project_id = _create_project(client, "web-sync-headless-policy")
    observed: dict[str, object] = {}

    class _DummyWebLoader:
        def __init__(self, **kwargs):
            observed.update(kwargs)
            self.last_stats = {}
            self.last_errors = []

        def load(self):
            return [LCDocument(page_content="sync web content", metadata={"source": "https://example.com"})]

    monkeypatch.setattr("rag_lib.loaders.web.WebLoader", _DummyWebLoader)

    response = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url",
        json={
            "loader_type": "web",
            "loader_params": {
                "url": "https://example.com",
                "depth": 0,
                "fetch_mode": "playwright",
                "playwright_headless": False,
                "playwright_visible": True,
            },
        },
    )
    assert response.status_code == 200, response.text
    assert observed["playwright_headless"] is True
    assert observed["playwright_visible"] is False
    params = response.json()["document_set"]["params"]["loader_params"]
    assert params["playwright_headless"] is True
    assert params["playwright_visible"] is False


def test_async_web_loader_forces_playwright_headless(client, monkeypatch):
    project_id = _create_project(client, "web-async-headless-policy")
    observed: dict[str, object] = {}

    class _DummyAsyncWebLoader:
        def __init__(self, **kwargs):
            observed.update(kwargs)
            self.last_stats = {}
            self.last_errors = []

        async def load(self):
            return [LCDocument(page_content="async web content", metadata={"source": "https://example.com/async"})]

    monkeypatch.setattr("rag_lib.loaders.web_async.AsyncWebLoader", _DummyAsyncWebLoader)

    response = client.post(
        f"/api/v1/projects/{project_id}/load_documents/url",
        json={
            "loader_type": "web_async",
            "loader_params": {
                "url": "https://example.com/async",
                "depth": 0,
                "fetch_mode": "playwright",
                "playwright_headless": False,
                "playwright_visible": True,
            },
        },
    )
    assert response.status_code == 200, response.text
    assert observed["playwright_headless"] is True
    assert observed["playwright_visible"] is False
    params = response.json()["document_set"]["params"]["loader_params"]
    assert params["playwright_headless"] is True
    assert params["playwright_visible"] is False
