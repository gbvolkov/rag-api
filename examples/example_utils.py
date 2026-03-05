from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from examples.api_client import ApiClient, ApiClientError


def print_section(index: int, title: str) -> None:
    print(f"\n{index}. {title}")


def print_kv(title: str, data: dict[str, Any]) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"

    def _safe(value: Any) -> str:
        text = str(value)
        try:
            text.encode(encoding)
            return text
        except UnicodeEncodeError:
            return text.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")

    print(title)
    for key, value in data.items():
        print(f"  - {key}: {_safe(value)}")


def print_api_error(exc: ApiClientError) -> None:
    payload = exc.payload if isinstance(exc.payload, dict) else {}
    detail = payload.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code") or payload.get("code")
        message = detail.get("message") or payload.get("message") or str(exc)
        hint = detail.get("hint") or payload.get("hint")
    else:
        code = payload.get("code")
        message = payload.get("message") or (detail if isinstance(detail, str) else None) or payload.get("raw") or str(exc)
        hint = payload.get("hint")
    print(f"API error: code={code} status={exc.status_code} message={message}")
    if hint:
        print(f"Hint: {hint}")
    raw = payload.get("raw")
    if isinstance(raw, str) and raw.strip():
        preview = raw.replace("\r", " ").replace("\n", " ")
        if len(preview) > 400:
            preview = preview[:400] + "..."
        print(f"Raw response: {preview}")


def default_client(timeout_seconds: float | None = None) -> ApiClient:
    base = os.getenv("RAG_API_BASE_URL", "http://127.0.0.1:8000/api/v1")
    timeout = timeout_seconds if timeout_seconds is not None else float(os.getenv("RAG_API_TIMEOUT_SECONDS", "120"))
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _api_get(api: Any, path: str) -> Any:
    if hasattr(api, "_request"):
        return api._request("GET", path)
    raise RuntimeError("API client does not support GET requests")


def _api_get_optional(api: Any, path: str, default: Any) -> tuple[Any, dict[str, Any] | None]:
    try:
        return _api_get(api, path), None
    except ApiClientError as exc:
        return (
            default,
            {
                "path": path,
                "status_code": exc.status_code,
                "payload": exc.payload,
            },
        )


def _as_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    return []


def _list_project_artifacts(api: Any, project_id: str, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    pages_fetched = 0

    while True:
        path = f"/projects/{project_id}/artifacts?limit=200"
        if cursor:
            path = f"{path}&cursor={quote_plus(cursor)}"

        page, warning = _api_get_optional(api, path, default={})
        if warning:
            warnings.append(warning)
            break

        if not isinstance(page, dict):
            warnings.append({"path": path, "message": "unexpected_artifacts_response_type"})
            break

        batch = page.get("items")
        if not isinstance(batch, list):
            warnings.append({"path": path, "message": "unexpected_artifacts_items_type"})
            break

        items.extend(batch)
        pages_fetched += 1

        has_more = bool(page.get("has_more"))
        next_cursor = page.get("next_cursor")
        if not has_more or not next_cursor:
            break
        cursor = str(next_cursor)

    return {
        "items": items,
        "total": len(items),
        "pages_fetched": pages_fetched,
    }


def _write_bundle_json(bundle_dir: Path, relative_path: str, payload: Any, written_paths: list[Path]) -> Path:
    out = bundle_dir / relative_path
    _write_pretty_json(out, payload)
    written_paths.append(out)
    return out


def export_results_json(api: Any, project_id: str, example_id: str) -> list[Path]:
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    bundle_dir = results_dir / f"{example_id}_bundle_{timestamp}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[dict[str, Any]] = []

    project, warning = _api_get_optional(api, f"/projects/{project_id}", default={})
    if warning:
        warnings.append(warning)

    documents, warning = _api_get_optional(api, f"/projects/{project_id}/documents", default=[])
    if warning:
        warnings.append(warning)
    documents = _as_list(documents)

    document_versions: dict[str, list[dict[str, Any]]] = {}
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        document_id = doc.get("document_id")
        if not document_id:
            continue
        versions, warning = _api_get_optional(api, f"/documents/{document_id}/versions", default=[])
        if warning:
            warnings.append(warning)
        document_versions[str(document_id)] = _as_list(versions)

    segment_set_summaries, warning = _api_get_optional(api, f"/projects/{project_id}/segment_sets", default=[])
    if warning:
        warnings.append(warning)
    segment_set_summaries = _as_list(segment_set_summaries)

    segment_set_details: list[dict[str, Any]] = []
    for summary in segment_set_summaries:
        if not isinstance(summary, dict):
            continue
        segment_set_id = summary.get("segment_set_version_id")
        if not segment_set_id:
            continue
        detail, warning = _api_get_optional(api, f"/segment_sets/{segment_set_id}", default=None)
        if warning:
            warnings.append(warning)
            continue
        if isinstance(detail, dict):
            segment_set_details.append(detail)

    segment_sets_by_document_version: dict[str, list[str]] = {}
    for summary in segment_set_summaries:
        if not isinstance(summary, dict):
            continue
        segment_set_id = summary.get("segment_set_version_id")
        if not segment_set_id:
            continue
        doc_version_id = str(summary.get("document_version_id") or "__none__")
        segment_sets_by_document_version.setdefault(doc_version_id, []).append(str(segment_set_id))

    retrieval_runs, warning = _api_get_optional(api, f"/projects/{project_id}/retrieval_runs", default=[])
    if warning:
        warnings.append(warning)
    retrieval_runs = _as_list(retrieval_runs)

    retrieval_results: list[dict[str, Any]] = []
    for run in retrieval_runs:
        if not isinstance(run, dict):
            continue
        run_id = run.get("run_id")
        if not run_id:
            continue
        detail, warning = _api_get_optional(api, f"/retrieval_runs/{run_id}", default=None)
        if warning:
            warnings.append(warning)
            continue
        if isinstance(detail, dict):
            retrieval_results.append(detail)

    raptor_runs, warning = _api_get_optional(api, f"/projects/{project_id}/raptor_runs", default=[])
    if warning:
        warnings.append(warning)
    raptor_runs = _as_list(raptor_runs)

    indexes, warning = _api_get_optional(api, f"/projects/{project_id}/indexes", default=[])
    if warning:
        warnings.append(warning)
    indexes = _as_list(indexes)

    index_details: list[dict[str, Any]] = []
    index_builds_by_index: dict[str, list[dict[str, Any]]] = {}
    index_build_details: list[dict[str, Any]] = []
    for index_summary in indexes:
        if not isinstance(index_summary, dict):
            continue
        index_id = index_summary.get("index_id")
        if not index_id:
            continue

        index_detail, warning = _api_get_optional(api, f"/indexes/{index_id}", default=None)
        if warning:
            warnings.append(warning)
        elif isinstance(index_detail, dict):
            index_details.append(index_detail)

        builds, warning = _api_get_optional(api, f"/indexes/{index_id}/builds", default=[])
        if warning:
            warnings.append(warning)
            builds = []
        builds_list = _as_list(builds)
        index_builds_by_index[str(index_id)] = builds_list

        for build in builds_list:
            if not isinstance(build, dict):
                continue
            build_id = build.get("build_id")
            if not build_id:
                continue
            build_detail, warning = _api_get_optional(api, f"/index_builds/{build_id}", default=None)
            if warning:
                warnings.append(warning)
                continue
            if isinstance(build_detail, dict):
                index_build_details.append(build_detail)

    graph_builds, warning = _api_get_optional(api, f"/projects/{project_id}/graph/builds", default=[])
    if warning:
        warnings.append(warning)
    graph_builds = _as_list(graph_builds)

    graph_build_details: list[dict[str, Any]] = []
    for build in graph_builds:
        if not isinstance(build, dict):
            continue
        graph_build_id = build.get("graph_build_id")
        if not graph_build_id:
            continue
        detail, warning = _api_get_optional(api, f"/graph_builds/{graph_build_id}", default=None)
        if warning:
            warnings.append(warning)
            continue
        if isinstance(detail, dict):
            graph_build_details.append(detail)

    artifacts = _list_project_artifacts(api, project_id, warnings)

    legacy_files = [
        (f"{example_id}_documents_{timestamp}.json", documents),
        (f"{example_id}_segments_{timestamp}.json", segment_set_details),
        (f"{example_id}_retrieval_results_{timestamp}.json", retrieval_results),
    ]

    written_paths: list[Path] = []
    legacy_paths: list[Path] = []
    for filename, payload in legacy_files:
        output_path = results_dir / filename
        _write_pretty_json(output_path, payload)
        written_paths.append(output_path)
        legacy_paths.append(output_path)

    _write_bundle_json(bundle_dir, "project.json", project, written_paths)
    _write_bundle_json(bundle_dir, "documents.json", documents, written_paths)
    _write_bundle_json(bundle_dir, "document_versions.json", document_versions, written_paths)
    _write_bundle_json(bundle_dir, "segment_sets/index.json", segment_set_summaries, written_paths)
    _write_bundle_json(bundle_dir, "segment_sets/by_document_version.json", segment_sets_by_document_version, written_paths)
    _write_bundle_json(bundle_dir, "segment_sets/all_details.json", segment_set_details, written_paths)

    for idx, detail in enumerate(segment_set_details, start=1):
        segment_set = detail.get("segment_set", {}) if isinstance(detail, dict) else {}
        segment_set_id = segment_set.get("segment_set_version_id") if isinstance(segment_set, dict) else None
        slug = str(segment_set_id or f"unknown_{idx}")
        _write_bundle_json(bundle_dir, f"segment_sets/{idx:03d}_{slug}.json", detail, written_paths)

    _write_bundle_json(bundle_dir, "retrieval_runs/index.json", retrieval_runs, written_paths)
    _write_bundle_json(bundle_dir, "retrieval_runs/all_details.json", retrieval_results, written_paths)
    for idx, detail in enumerate(retrieval_results, start=1):
        run_id = detail.get("run_id") if isinstance(detail, dict) else None
        slug = str(run_id or f"unknown_{idx}")
        _write_bundle_json(bundle_dir, f"retrieval_runs/{idx:03d}_{slug}.json", detail, written_paths)

    _write_bundle_json(bundle_dir, "raptor_runs/index.json", raptor_runs, written_paths)

    _write_bundle_json(bundle_dir, "indexes/index.json", indexes, written_paths)
    _write_bundle_json(bundle_dir, "indexes/all_details.json", index_details, written_paths)
    _write_bundle_json(bundle_dir, "indexes/builds_by_index.json", index_builds_by_index, written_paths)
    _write_bundle_json(bundle_dir, "index_builds/all_details.json", index_build_details, written_paths)

    for idx, detail in enumerate(index_details, start=1):
        index_id = detail.get("index_id") if isinstance(detail, dict) else None
        slug = str(index_id or f"unknown_{idx}")
        _write_bundle_json(bundle_dir, f"indexes/{idx:03d}_{slug}.json", detail, written_paths)

    for idx, detail in enumerate(index_build_details, start=1):
        build_id = detail.get("build_id") if isinstance(detail, dict) else None
        slug = str(build_id or f"unknown_{idx}")
        _write_bundle_json(bundle_dir, f"index_builds/{idx:03d}_{slug}.json", detail, written_paths)

    _write_bundle_json(bundle_dir, "graph_builds/index.json", graph_builds, written_paths)
    _write_bundle_json(bundle_dir, "graph_builds/all_details.json", graph_build_details, written_paths)
    for idx, detail in enumerate(graph_build_details, start=1):
        graph_build_id = detail.get("graph_build_id") if isinstance(detail, dict) else None
        slug = str(graph_build_id or f"unknown_{idx}")
        _write_bundle_json(bundle_dir, f"graph_builds/{idx:03d}_{slug}.json", detail, written_paths)

    _write_bundle_json(bundle_dir, "artifacts/index.json", artifacts, written_paths)

    bundle_paths = [p for p in written_paths if p not in legacy_paths]
    manifest = {
        "example_id": example_id,
        "project_id": project_id,
        "generated_at": datetime.now().isoformat(),
        "timestamp": timestamp,
        "bundle_dir": str(bundle_dir),
        "counts": {
            "documents": len(documents),
            "document_versions": sum(len(v) for v in document_versions.values()),
            "segment_set_summaries": len(segment_set_summaries),
            "segment_set_details": len(segment_set_details),
            "retrieval_runs": len(retrieval_runs),
            "retrieval_run_details": len(retrieval_results),
            "raptor_runs": len(raptor_runs),
            "indexes": len(indexes),
            "index_details": len(index_details),
            "index_builds": len(index_build_details),
            "graph_builds": len(graph_builds),
            "graph_build_details": len(graph_build_details),
            "artifacts": len(_as_list(artifacts.get("items")) if isinstance(artifacts, dict) else []),
        },
        "segment_sets_by_document_version": segment_sets_by_document_version,
        "legacy_files": [str(p.relative_to(results_dir)) for p in legacy_paths],
        "bundle_files": [str(p.relative_to(bundle_dir)) for p in bundle_paths],
        "warnings": warnings,
    }
    _write_bundle_json(bundle_dir, "manifest.json", manifest, written_paths)
    return written_paths
