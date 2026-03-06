import time

from examples.api_client import ApiClientError
from examples.example_utils import default_client, export_results_json, print_api_error, print_kv, print_section, project_name


TARGET_URL = "https://quotes.toscrape.com"
CLEANUP_CONFIG = {
    "duplicate_tags": [],
    "non_recursive_classes": ["tag"],
    "navigation_classes": ["side_categories", "pager"],
    "ignored_classes": [
        "footer",
        "row header-box",
        "breadcrumb",
        "header container-fluid",
        "icon-star",
        "image_container",
    ],
}
SYNC_WEB_LOADER_PARAMS = {
    "url": TARGET_URL,
    "depth": 3,
    "output_format": "markdown",
    "fetch_mode": "requests",
    "crawl_scope": "same_host",
    "follow_download_links": False,
    "cleanup_config": CLEANUP_CONFIG,
}
ASYNC_WEB_LOADER_PARAMS = {
    "url": TARGET_URL,
    "depth": 3,
    "output_format": "markdown",
    "fetch_mode": "playwright",
    "crawl_scope": "same_host",
    "follow_download_links": False,
    "max_concurrency": 4,
    "cleanup_config": CLEANUP_CONFIG,
}
RECURSIVE_SPLITTER_PARAMS = {"chunk_size": 1200, "chunk_overlap": 120}
URL_LOAD_POLL_INTERVAL_SECONDS = 2.0
URL_LOAD_MAX_WAIT_SECONDS = 900.0


def _segment_preview(segment_items: list[dict]) -> dict:
    if not segment_items:
        return {"items": 0}

    first = segment_items[0]
    return {"items": len(segment_items), "content_preview": (first.get("content") or "")[:120]}


def _wait_for_job(api, job_id: str) -> dict:
    started = time.monotonic()
    while True:
        job = api.get_job(job_id)
        status = job.get("status")
        if status == "succeeded":
            return job
        if status == "failed":
            raise ApiClientError(
                f"URL load job failed: {job_id}",
                payload={"detail": {"code": "url_load_job_failed", "message": job.get("error_message") or "unknown error"}},
            )
        if URL_LOAD_MAX_WAIT_SECONDS is not None and (time.monotonic() - started) > URL_LOAD_MAX_WAIT_SECONDS:
            raise ApiClientError(
                f"URL load job timed out: {job_id}",
                payload={
                    "detail": {
                        "code": "url_load_job_timeout",
                        "message": f"Job did not finish within {URL_LOAD_MAX_WAIT_SECONDS:.0f} seconds",
                    }
                },
            )
        time.sleep(URL_LOAD_POLL_INTERVAL_SECONDS)


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "17B-web-loader-quotes", "title": "Web loader quotes workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("17B-web-loader-quotes"), description=artifacts["title"])
        project_id = project["project_id"]
        artifacts["project_id"] = project_id
        print_kv("Project created", {"project_id": project_id})
        section += 1

        print_section(section, "Load URL documents (sync web)")
        sync_submit = api.submit_load_documents_from_url(project_id, loader_type="web", loader_params=SYNC_WEB_LOADER_PARAMS)
        artifacts["sync_url_load_job_id"] = sync_submit["job_id"]
        sync_job = _wait_for_job(api, artifacts["sync_url_load_job_id"])
        sync_result = sync_job.get("result") or {}
        sync_document_set_version_id = sync_result["document_set_version_id"]
        artifacts["document_set_version_id"] = sync_document_set_version_id
        seg_sync = api.create_segments(
            sync_document_set_version_id,
            split_strategy="recursive",
            splitter_params=RECURSIVE_SPLITTER_PARAMS,
        )
        sync_segment_set_version_id = seg_sync["segment_set"]["segment_set_version_id"]
        artifacts["segment_set_version_id"] = sync_segment_set_version_id
        print_kv(
            "URL segments created",
            {
                "job_id": artifacts["sync_url_load_job_id"],
                "document_set_version_id": sync_document_set_version_id,
                "document_items": sync_result.get("total_items", 0),
                "segment_set_version_id": sync_segment_set_version_id,
                **_segment_preview(seg_sync["items"]),
            },
        )
        section += 1

        print_section(section, "Load URL documents (async web)")
        async_submit = api.submit_load_documents_from_url(project_id, loader_type="web_async", loader_params=ASYNC_WEB_LOADER_PARAMS)
        artifacts["async_url_load_job_id"] = async_submit["job_id"]
        async_job = _wait_for_job(api, artifacts["async_url_load_job_id"])
        async_result = async_job.get("result") or {}
        async_document_set_version_id = async_result["document_set_version_id"]
        artifacts["async_document_set_version_id"] = async_document_set_version_id
        seg_async = api.create_segments(
            async_document_set_version_id,
            split_strategy="recursive",
            splitter_params=RECURSIVE_SPLITTER_PARAMS,
        )
        async_segment_set_version_id = seg_async["segment_set"]["segment_set_version_id"]
        artifacts["async_segment_set_version_id"] = async_segment_set_version_id
        print_kv(
            "URL segments created",
            {
                "job_id": artifacts["async_url_load_job_id"],
                "document_set_version_id": async_document_set_version_id,
                "document_items": async_result.get("total_items", 0),
                "segment_set_version_id": async_segment_set_version_id,
                **_segment_preview(seg_async["items"]),
            },
        )
        section += 1
    except ApiClientError as exc:
        artifacts["status"] = "error"
        artifacts["error_status_code"] = exc.status_code
        artifacts["error_payload"] = exc.payload
        print_api_error(exc)
        raise

    export_results_json(api, artifacts["project_id"], artifacts["example_id"])
    print_section(section, "Artifacts saved")
    print_kv("Artifacts", artifacts)
    return artifacts


if __name__ == "__main__":
    run_example()
