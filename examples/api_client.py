from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


class ApiClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class ApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def _url(self, path: str) -> str:
        if path.startswith("/"):
            return f"{self.base_url}{path}"
        return f"{self.base_url}/{path}"

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        response = self.client.request(method, self._url(path), **kwargs)
        if response.status_code >= 400:
            payload: dict[str, Any]
            try:
                payload = response.json()
            except Exception:
                payload = {"raw": response.text}
            raise ApiClientError(
                f"{method} {path} failed with {response.status_code}",
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

    def create_segments(
        self,
        version_id: str,
        loader_type: str,
        loader_params: dict[str, Any] | None = None,
        split_strategy: str | None = None,
        splitter_params: dict[str, Any] | None = None,
        source_text: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "loader_type": loader_type,
            "loader_params": loader_params or {},
            "split_strategy": split_strategy,
            "splitter_params": splitter_params or {},
        }
        if source_text is not None:
            payload["source_text"] = source_text
        return self._request("POST", f"/document_versions/{version_id}/segments", json=payload)

    def create_segments_from_url(
        self,
        project_id: str,
        loader_type: str,
        loader_params: dict[str, Any],
        split_strategy: str | None = None,
        splitter_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/projects/{project_id}/segments/url",
            json={
                "loader_type": loader_type,
                "loader_params": loader_params,
                "split_strategy": split_strategy,
                "splitter_params": splitter_params or {},
            },
        )

    def create_chunks(self, segment_set_id: str, strategy: str, chunker_params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", f"/segment_sets/{segment_set_id}/chunk", json={"strategy": strategy, "chunker_params": chunker_params or {}})

    def create_chunks_from_chunk_set(self, chunk_set_id: str, strategy: str, chunker_params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", f"/chunk_sets/{chunk_set_id}/chunk", json={"strategy": strategy, "chunker_params": chunker_params or {}})

    def create_index(self, project_id: str, name: str, provider: str, config: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/projects/{project_id}/indexes",
            json={"name": name, "provider": provider, "index_type": "chunk_vectors", "config": config or {}, "params": params or {}},
        )

    def create_index_build(
        self,
        index_id: str,
        chunk_set_version_id: str,
        execution_mode: str = "sync",
        params: dict[str, Any] | None = None,
        doc_store: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chunk_set_version_id": chunk_set_version_id,
            "execution_mode": execution_mode,
            "params": params or {},
        }
        if doc_store is not None:
            payload["doc_store"] = doc_store
        return self._request(
            "POST",
            f"/indexes/{index_id}/builds",
            json=payload,
        )

    def create_graph_build(self, project_id: str, source_type: str, source_id: str, execution_mode: str = "sync", backend: str = "networkx", params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "source_type": source_type,
            "source_id": source_id,
            "backend": backend,
            "execution_mode": execution_mode,
            "extract_entities": False,
            "detect_communities": False,
            "summarize_communities": False,
        }
        if params:
            payload.update(params)
        return self._request("POST", f"/projects/{project_id}/graph/builds", json=payload)

    def run_raptor(self, segment_set_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/segment_sets/{segment_set_id}/raptor", json=payload)

    def run_enrich(self, segment_set_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/segment_sets/{segment_set_id}/enrich", json=payload)

    def list_raptor_runs(self, project_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/projects/{project_id}/raptor_runs")

    def retrieve(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/projects/{project_id}/retrieve", json=payload)

    def list_retrieval_runs(self, project_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/projects/{project_id}/retrieval_runs")
