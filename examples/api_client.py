from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


class ApiClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.base_url_ipv4 = self._localhost_to_ipv4(self.base_url)
        self.timeout_seconds = timeout_seconds
        self.client = self._new_client()

    def _new_client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout_seconds)

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _localhost_to_ipv4(url: str) -> str | None:
        try:
            parts = urlsplit(url)
        except Exception:
            return None
        if parts.hostname != "localhost":
            return None
        hostname = "127.0.0.1"
        if parts.port is not None:
            hostname = f"{hostname}:{parts.port}"
        if parts.username:
            auth = parts.username
            if parts.password:
                auth += f":{parts.password}"
            hostname = f"{auth}@{hostname}"
        return urlunsplit((parts.scheme, hostname, parts.path, parts.query, parts.fragment)).rstrip("/")

    def _url(self, path: str, base_url: str | None = None) -> str:
        root = (base_url or self.base_url).rstrip("/")
        if path.startswith("/"):
            return f"{root}{path}"
        return f"{root}/{path}"

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        base_urls = [self.base_url]
        if self.base_url_ipv4 and self.base_url_ipv4 != self.base_url:
            base_urls.append(self.base_url_ipv4)

        response: httpx.Response | None = None
        last_transport_error: httpx.TransportError | None = None
        attempted_urls: list[str] = []

        # Short retries handle stale keep-alive sockets and transient disconnects
        # (e.g., WinError 10054). If base_url is localhost, also try 127.0.0.1.
        for base in base_urls:
            url = self._url(path, base_url=base)
            attempted_urls.append(url)
            for attempt in range(2):
                try:
                    response = self.client.request(method, url, **kwargs)
                    last_transport_error = None
                    if base != self.base_url:
                        self.base_url = base
                        self.base_url_ipv4 = self._localhost_to_ipv4(self.base_url)
                    break
                except httpx.TransportError as exc:
                    last_transport_error = exc
                    if attempt == 1:
                        break
                    try:
                        self.client.close()
                    finally:
                        self.client = self._new_client()
                    time.sleep(0.25 * (attempt + 1))
            if response is not None:
                break

        if last_transport_error is not None or response is None:
            exc = last_transport_error or RuntimeError("unknown transport error")
            raise ApiClientError(
                f"{method} {attempted_urls[-1]} transport error: {type(exc).__name__}: {exc}",
                payload={
                    "code": "transport_error",
                    "message": str(exc),
                    "detail": {
                        "method": method,
                        "url": attempted_urls[-1],
                        "attempted_urls": attempted_urls,
                        "exception_type": type(exc).__name__,
                    },
                },
            )
        if response.status_code >= 400:
            payload: dict[str, Any]
            try:
                payload = response.json()
            except Exception:
                payload = {"raw": response.text}
            detail_message: str | None = None
            if isinstance(payload, dict):
                detail = payload.get("detail")
                if isinstance(detail, dict):
                    detail_message = detail.get("message") or detail.get("code")
                elif isinstance(detail, str):
                    detail_message = detail
                if not detail_message:
                    message = payload.get("message")
                    if isinstance(message, str):
                        detail_message = message
                if not detail_message:
                    raw = payload.get("raw")
                    if isinstance(raw, str) and raw.strip():
                        detail_message = raw.strip()
            if detail_message:
                detail_message = detail_message.replace("\r", " ").replace("\n", " ")
                if len(detail_message) > 200:
                    detail_message = detail_message[:200] + "..."
            raise ApiClientError(
                (
                    f"{method} {url} failed with {response.status_code}"
                    + (f" ({detail_message})" if detail_message else "")
                ),
                status_code=response.status_code,
                payload=payload,
            )
        if not response.content:
            return {}
        return response.json()

    def create_project(self, name: str, description: str = "") -> dict[str, Any]:
        return self._request("POST", "/projects", json={"name": name, "description": description, "settings": {}})

    def upload_document(self, project_id: str, file_path: Path, mime: str, parser_params: dict[str, Any] | None = None) -> dict[str, Any]:
        parser_params = parser_params or {}
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f, mime)}
            data = {"parser_params_json": json.dumps(parser_params)}
            return self._request("POST", f"/projects/{project_id}/documents", files=files, data=data)

    def load_documents(
        self,
        version_id: str,
        loader_type: str | None = None,
        loader_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/document_versions/{version_id}/load_documents",
            json={
                "loader_type": loader_type,
                "loader_params": loader_params or {},
            },
        )

    def load_documents_from_url(
        self,
        project_id: str,
        loader_type: str | None = None,
        loader_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/projects/{project_id}/load_documents/url",
            json={
                "loader_type": loader_type,
                "loader_params": loader_params or {},
            },
        )

    def list_document_sets(self, project_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/projects/{project_id}/document_sets")

    def get_document_set(self, document_set_version_id: str) -> dict[str, Any]:
        return self._request("GET", f"/document_sets/{document_set_version_id}")

    def create_segments(
        self,
        document_set_version_id: str,
        split_strategy: str,
        splitter_params: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/document_sets/{document_set_version_id}/segments",
            json={
                "split_strategy": split_strategy,
                "splitter_params": splitter_params or {},
                "params": params or {},
            },
        )

    def split_segment_set(
        self,
        segment_set_id: str,
        strategy: str,
        splitter_params: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/segment_sets/{segment_set_id}/split",
            json={
                "strategy": strategy,
                "splitter_params": splitter_params or {},
                "params": params or {},
            },
        )

    def create_index(self, project_id: str, name: str, provider: str, config: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/projects/{project_id}/indexes",
            json={"name": name, "provider": provider, "index_type": "segment_vectors", "config": config or {}, "params": params or {}},
        )

    def create_index_build(
        self,
        index_id: str,
        source_set_id: str,
        execution_mode: str = "sync",
        params: dict[str, Any] | None = None,
        parent_set_id: str | None = None,
        id_key: str | None = None,
        doc_store: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_set_id": source_set_id,
            "execution_mode": execution_mode,
            "params": params or {},
        }
        if parent_set_id is not None:
            payload["parent_set_id"] = parent_set_id
        if id_key is not None:
            payload["id_key"] = id_key
        if doc_store is not None:
            payload["doc_store"] = doc_store
        return self._request(
            "POST",
            f"/indexes/{index_id}/builds",
            json=payload,
        )

    def create_graph_build(
        self,
        project_id: str,
        source_type: str,
        source_id: str,
        execution_mode: str = "sync",
        backend: str = "networkx",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_type": source_type,
            "source_id": source_id,
            "backend": backend,
            "execution_mode": execution_mode,
            "extract_entities": False,
            "detect_communities": False,
            "summarize_communities": False,
            "params": {},
        }

        extra = dict(params or {})
        top_level_fields = {
            "extract_entities",
            "detect_communities",
            "summarize_communities",
            "llm_provider",
            "llm_model",
            "llm_temperature",
            "search_depth",
        }
        for key in top_level_fields:
            if key in extra:
                payload[key] = extra.pop(key)

        nested = extra.pop("params", None)
        if isinstance(nested, dict):
            payload["params"].update(nested)
        if extra:
            payload["params"].update(extra)

        return self._request("POST", f"/projects/{project_id}/graph/builds", json=payload)

    def run_raptor(self, segment_set_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/segment_sets/{segment_set_id}/raptor", json=payload)

    def run_enrich(self, segment_set_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/segment_sets/{segment_set_id}/enrich", json=payload)

    def list_raptor_runs(self, project_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/projects/{project_id}/raptor_runs")

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/jobs/{job_id}")

    def retrieve(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/projects/{project_id}/retrieve", json=payload)

    def list_retrieval_runs(self, project_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/projects/{project_id}/retrieval_runs")
