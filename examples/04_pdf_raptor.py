import time

from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name

RAPTOR_POLL_INTERVAL_SECONDS = 2.0
RAPTOR_MAX_WAIT_SECONDS = 900.0
RAPTOR_SUBMIT_RETRIES = 2
RAPTOR_SUBMIT_RETRY_SECONDS = 2.0


def _wait_for_job(api, job_id: str) -> dict:
    started = time.monotonic()
    while True:
        job = api.get_job(job_id)
        status = job.get("status")
        if status == "succeeded":
            return job
        if status == "failed":
            raise ApiClientError(
                f"RAPTOR job failed: {job_id}",
                payload={"detail": {"code": "raptor_job_failed", "message": job.get("error_message") or "unknown error"}},
            )
        if RAPTOR_MAX_WAIT_SECONDS is not None and (time.monotonic() - started) > RAPTOR_MAX_WAIT_SECONDS:
            raise ApiClientError(
                f"RAPTOR job timed out: {job_id}",
                payload={
                    "detail": {
                        "code": "raptor_job_timeout",
                        "message": f"Job did not finish within {RAPTOR_MAX_WAIT_SECONDS:.0f} seconds",
                    }
                },
            )
        time.sleep(RAPTOR_POLL_INTERVAL_SECONDS)


def _submit_raptor_async(api, segment_set_id: str, payload: dict) -> dict:
    for attempt in range(RAPTOR_SUBMIT_RETRIES + 1):
        try:
            return api.run_raptor(segment_set_id, payload)
        except ApiClientError as exc:
            retryable = exc.status_code in {502, 503, 504}
            if not retryable or attempt >= RAPTOR_SUBMIT_RETRIES:
                raise
            sleep_for = RAPTOR_SUBMIT_RETRY_SECONDS * (attempt + 1)
            print_kv(
                "RAPTOR submit retry",
                {
                    "attempt": f"{attempt + 1}/{RAPTOR_SUBMIT_RETRIES}",
                    "status_code": exc.status_code,
                    "sleep_seconds": sleep_for,
                },
            )
            time.sleep(sleep_for)
    raise RuntimeError("Unreachable RAPTOR submit retry state")


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "04-pdf-raptor", "title": "PDF RAPTOR workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("04-pdf-raptor"), description=artifacts["title"])
        artifacts["project_id"] = project["project_id"]
        print_kv("Project created", {"project_id": artifacts["project_id"]})
        section += 1

        pdf_file = "Georgy Volkov ru.pdf"

        print_section(section, "Ingest source document")
        upload = api.upload_document(artifacts["project_id"], docs_path(pdf_file), "application/pdf")
        artifacts["document_id"] = upload["document"]["document_id"]
        artifacts["document_version_id"] = upload["document_version"]["version_id"]
        artifacts["source_pdf"] = pdf_file
        print_kv(
            "Document uploaded",
            {"document_id": artifacts["document_id"], "document_version_id": artifacts["document_version_id"]},
        )
        section += 1

        print_section(section, "Load documents (pdf loader)")
        loaded = api.load_documents(
            artifacts["document_version_id"],
            loader_type="pdf",
            loader_params={"parse_mode": "text"},
        )
        artifacts["document_set_version_id"] = loaded["document_set"]["document_set_version_id"]
        print_kv(
            "Documents loaded",
            {"document_set_version_id": artifacts["document_set_version_id"], "items": len(loaded["items"])},
        )
        section += 1

        print_section(section, "Create segments (sentence splitter)")
        seg = api.create_segments(
            artifacts["document_set_version_id"],
            split_strategy="sentence",
            splitter_params={"chunk_size": 200, "chunk_overlap": 20, "language": "auto"},
        )
        artifacts["segment_set_version_id"] = seg["segment_set"]["segment_set_version_id"]
        print_kv(
            "Segments created",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "items": len(seg["items"])},
        )
        section += 1

        print_section(section, "Run RAPTOR")
        source_segment_set_id = artifacts["segment_set_version_id"]
        rap = _submit_raptor_async(
            api,
            artifacts["segment_set_version_id"],
            {
                "execution_mode": "async",
                "max_levels": 3,
                "llm_provider": "openai",
                "llm_model": "gpt-4.1-nano",
                "llm_temperature": 0,
                "embedding_provider": "openai",
            },
        )
        artifacts["raptor_job_id"] = rap["job_id"]
        job = _wait_for_job(api, artifacts["raptor_job_id"])
        result = job.get("result") or {}
        artifacts["segment_set_version_id"] = result["segment_set_version_id"]
        runs = api.list_raptor_runs(artifacts["project_id"])
        run = next(
            (
                r
                for r in runs
                if r.get("source_segment_set_version_id") == source_segment_set_id
                and r.get("output_segment_set_version_id") == artifacts["segment_set_version_id"]
            ),
            None,
        )
        artifacts["raptor_run_id"] = run.get("raptor_run_id") if run else None
        print_kv(
            "RAPTOR completed",
            {
                "raptor_job_id": artifacts["raptor_job_id"],
                "segment_set_version_id": artifacts["segment_set_version_id"],
                "raptor_run_id": artifacts["raptor_run_id"],
            },
        )
        section += 1

        print_section(section, "Create index source chunks from RAPTOR tree")
        chunk = api.split_segment_set(
            artifacts["segment_set_version_id"],
            strategy="sentence",
            splitter_params={"chunk_size": 200, "chunk_overlap": 20, "language": "auto"},
        )
        artifacts["source_set_id"] = chunk["segment_set"]["segment_set_version_id"]
        print_kv(
            "Chunks created",
            {"source_set_id": artifacts["source_set_id"], "items": len(chunk["items"])},
        )
        section += 1

        print_section(section, "Create index and build")
        idx = api.create_index(
            artifacts["project_id"],
            "04_pdf_raptor",
            provider="chroma",
            config={"embedding_provider": "openai", "collection_name": "04_pdf_raptor"},
        )
        artifacts["index_id"] = idx["index_id"]
        build = api.create_index_build(
            artifacts["index_id"],
            artifacts["source_set_id"],
            execution_mode="sync",
            parent_set_id=artifacts["segment_set_version_id"],
            id_key="source_segment_item_id",
            doc_store={"backend": "local_file"},
        )
        artifacts["index_build_id"] = build["build"]["build_id"]
        print_kv(
            "Index build completed",
            {"index_id": artifacts["index_id"], "index_build_id": artifacts["index_build_id"]},
        )
        section += 1

        query = "CIO Europe"
        print_section(section, "Retrieve (scored dual storage)")
        retrieval = api.retrieve(
            artifacts["project_id"],
            {
                "query": query,
                "target": "index_build",
                "target_id": artifacts["index_build_id"],
                "strategy": {
                    "type": "dual_storage",
                    "vector_search": {"k": 10},
                    "search_kwargs": {"k": 10},
                    "id_key": "source_segment_item_id",
                    "search_type": "similarity_score_threshold",
                    "score_threshold": 0.0,
                    "hydration_mode": "children_enriched",
                },
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
