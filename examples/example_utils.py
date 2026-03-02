from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from examples.api_client import ApiClient, ApiClientError


def print_section(index: int, title: str) -> None:
    print(f"\n{index}. {title}")


def print_kv(title: str, data: dict[str, Any]) -> None:
    print(title)
    for key, value in data.items():
        print(f"  - {key}: {value}")


def print_api_error(exc: ApiClientError) -> None:
    detail = exc.payload.get("detail", {})
    code = detail.get("code") or exc.payload.get("code")
    message = detail.get("message") or exc.payload.get("message") or str(exc)
    hint = detail.get("hint")
    print(f"API error: code={code} status={exc.status_code} message={message}")
    if hint:
        print(f"Hint: {hint}")


def default_client() -> ApiClient:
    base = os.getenv("RAG_API_BASE_URL", "http://localhost:8000/api/v1")
    timeout = float(os.getenv("RAG_API_TIMEOUT_SECONDS", "120"))
    return ApiClient(base_url=base, timeout_seconds=timeout)


def project_name(example_id: str) -> str:
    prefix = os.getenv("RAG_API_PROJECT_NAME_PREFIX", "examples")
    return f"{prefix}-{example_id}"


def docs_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / filename


def docs_first(pattern: str) -> Path:
    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    matches = sorted(docs_dir.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No docs file matches pattern: {pattern}")
    return matches[0]


def _write_pretty_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _api_get(api: Any, path: str) -> Any:
    if hasattr(api, "_request"):
        return api._request("GET", path)
    raise RuntimeError("API client does not support GET requests")


def export_results_json(api: Any, project_id: str, example_id: str) -> list[Path]:
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    documents = _api_get(api, f"/projects/{project_id}/documents")

    segment_sets = _api_get(api, f"/projects/{project_id}/segment_sets")
    segments = []
    for segment_set in segment_sets:
        segment_set_id = segment_set.get("segment_set_version_id")
        if segment_set_id:
            segments.append(_api_get(api, f"/segment_sets/{segment_set_id}"))

    chunk_sets = _api_get(api, f"/projects/{project_id}/chunk_sets")
    chunks = []
    for chunk_set in chunk_sets:
        chunk_set_id = chunk_set.get("chunk_set_version_id")
        if chunk_set_id:
            chunks.append(_api_get(api, f"/chunk_sets/{chunk_set_id}"))

    retrieval_runs = _api_get(api, f"/projects/{project_id}/retrieval_runs")
    retrieval_results = []
    for run in retrieval_runs:
        run_id = run.get("run_id")
        if run_id:
            retrieval_results.append(_api_get(api, f"/retrieval_runs/{run_id}"))

    files = [
        (f"{example_id}_documents_{timestamp}.json", documents),
        (f"{example_id}_segments_{timestamp}.json", segments),
        (f"{example_id}_chunks_{timestamp}.json", chunks),
        (f"{example_id}_retrieval_results_{timestamp}.json", retrieval_results),
    ]
    written_paths: list[Path] = []
    for filename, payload in files:
        output_path = results_dir / filename
        _write_pretty_json(output_path, payload)
        written_paths.append(output_path)
    return written_paths
