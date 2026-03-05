import time

from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name

ENRICH_SEGMENT_LIMIT = 5
ENRICH_POLL_INTERVAL_SECONDS = 2.0
ENRICH_MAX_WAIT_SECONDS = None


def _wait_for_job(api, job_id: str) -> dict:
    started = time.monotonic()
    while True:
        job = api.get_job(job_id)
        status = job.get("status")
        if status == "succeeded":
            return job
        if status == "failed":
            raise ApiClientError(
                f"Enrichment job failed: {job_id}",
                payload={"detail": {"code": "enrich_job_failed", "message": job.get("error_message") or "unknown error"}},
            )
        if ENRICH_MAX_WAIT_SECONDS is not None and (time.monotonic() - started) > ENRICH_MAX_WAIT_SECONDS:
            raise ApiClientError(
                f"Enrichment job timed out: {job_id}",
                payload={
                    "detail": {
                        "code": "enrich_job_timeout",
                        "message": f"Job did not finish within {ENRICH_MAX_WAIT_SECONDS:.0f} seconds",
                    }
                },
            )
        time.sleep(ENRICH_POLL_INTERVAL_SECONDS)


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "02-markdown-enrichment", "title": "Markdown enrichment workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("02-markdown-enrichment"), description=artifacts["title"])
        artifacts["project_id"] = project["project_id"]
        print_kv("Project created", {"project_id": artifacts["project_id"]})
        section += 1

        print_section(section, "Ingest source document")
        upload = api.upload_document(artifacts["project_id"], docs_path("quotes.toscrape.com_index.md"), "text/markdown")
        artifacts["document_id"] = upload["document"]["document_id"]
        artifacts["document_version_id"] = upload["document_version"]["version_id"]
        print_kv(
            "Document uploaded",
            {"document_id": artifacts["document_id"], "document_version_id": artifacts["document_version_id"]},
        )
        section += 1

        print_section(section, "Load documents (text loader)")
        loaded = api.load_documents(artifacts["document_version_id"], loader_type="text", loader_params={})
        artifacts["document_set_version_id"] = loaded["document_set"]["document_set_version_id"]
        print_kv(
            "Documents loaded",
            {"document_set_version_id": artifacts["document_set_version_id"], "items": len(loaded["items"])},
        )
        section += 1

        print_section(section, "Create segments")
        seg = api.create_segments(artifacts["document_set_version_id"], split_strategy="identity")
        artifacts["segment_set_version_id"] = seg["segment_set"]["segment_set_version_id"]
        print_kv(
            "Segments created",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "items": len(seg["items"])},
        )
        section += 1

        print_section(section, "Create chunks (recursive)")
        chunk = api.split_segment_set(
            artifacts["segment_set_version_id"],
            strategy="recursive",
            splitter_params={"chunk_size": 1000, "chunk_overlap": 100},
        )
        artifacts["source_set_id"] = chunk["segment_set"]["segment_set_version_id"]
        print_kv(
            "Chunks created",
            {"source_set_id": artifacts["source_set_id"], "items": len(chunk["items"])},
        )
        section += 1

        if ENRICH_SEGMENT_LIMIT and len(chunk["items"]) > ENRICH_SEGMENT_LIMIT:
            artifacts["enrich_segment_limit"] = ENRICH_SEGMENT_LIMIT

        print_section(section, "Run enrichment")
        enr = api.run_enrich(
            artifacts["source_set_id"],
            {"execution_mode": "async", "llm_provider": "openai", "llm_model": "gpt-4.1-nano"},
        )
        artifacts["enrich_job_id"] = enr["job_id"]
        job = _wait_for_job(api, artifacts["enrich_job_id"])
        result = job.get("result") or {}
        artifacts["source_set_id"] = result["segment_set_version_id"]
        artifacts["segment_set_version_id"] = artifacts["source_set_id"]
        print_kv(
            "Enrichment completed",
            {
                "job_id": artifacts["enrich_job_id"],
                "source_set_id": artifacts["source_set_id"],
                "status": job.get("status"),
            },
        )
        section += 1

        print_section(section, "Retrieve (fuzzy)")
        retrieval = api.retrieve(
            artifacts["project_id"],
            {
                "query": "einstein",
                "target": "segment_set",
                "target_id": artifacts["segment_set_version_id"],
                "strategy": {"type": "fuzzy", "threshold": 45, "mode": "wratio"},
                "persist": True,
            },
        )
        artifacts["retrieval_run_ids"] = [retrieval.get("run_id")]
        print_kv("Retrieved", {"total": retrieval["total"], "run_id": retrieval.get("run_id")})
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
