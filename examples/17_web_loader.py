from examples.api_client import ApiClientError
from examples.example_utils import default_client, export_results_json, print_api_error, print_kv, print_section, project_name


TARGET_URL = "https://quotes.toscrape.com"


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "17-web-loader", "title": "Legacy web loader sync/async workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("17-web-loader"), description=artifacts["title"])
        artifacts["project_id"] = project["project_id"]
        print_kv("Project created", {"project_id": artifacts["project_id"]})
        section += 1

        print_section(section, "Load URL documents (sync web)")
        loaded_sync = api.load_documents_from_url(
            artifacts["project_id"],
            loader_type="web",
            loader_params={
                "url": TARGET_URL,
                "depth": 2,
                "output_format": "markdown",
                "fetch_mode": "requests",
                "crawl_scope": "same_host",
                "follow_download_links": False,
            },
        )
        artifacts["document_set_version_id"] = loaded_sync["document_set"]["document_set_version_id"]
        seg_sync = api.create_segments(
            artifacts["document_set_version_id"],
            split_strategy="identity",
        )
        artifacts["segment_set_version_id"] = seg_sync["segment_set"]["segment_set_version_id"]
        print_kv(
            "URL segments created",
            {
                "document_set_version_id": artifacts["document_set_version_id"],
                "segment_set_version_id": artifacts["segment_set_version_id"],
                "items": len(seg_sync["items"]),
            },
        )
        section += 1

        print_section(section, "Load URL documents (async web)")
        loaded_async = api.load_documents_from_url(
            artifacts["project_id"],
            loader_type="web_async",
            loader_params={
                "url": TARGET_URL,
                "depth": 2,
                "output_format": "markdown",
                "fetch_mode": "requests_fallback_playwright",
                "crawl_scope": "same_host",
                "follow_download_links": False,
                "max_concurrency": 4,
            },
        )
        artifacts["async_document_set_version_id"] = loaded_async["document_set"]["document_set_version_id"]
        seg_async = api.create_segments(
            artifacts["async_document_set_version_id"],
            split_strategy="identity",
        )
        artifacts["async_segment_set_version_id"] = seg_async["segment_set"]["segment_set_version_id"]
        print_kv(
            "URL segments created",
            {
                "document_set_version_id": artifacts["async_document_set_version_id"],
                "segment_set_version_id": artifacts["async_segment_set_version_id"],
                "items": len(seg_async["items"]),
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
