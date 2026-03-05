import time

from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name

GRAPH_POLL_INTERVAL_SECONDS = 2.0
GRAPH_MAX_WAIT_SECONDS = 900.0


def _graph_strategy(graph_build_id: str, mode: str) -> dict:
    if mode == "local":
        return {
            "type": "graph",
            "graph_build_id": graph_build_id,
            "mode": "local",
            "max_hops": 1,
            "top_k_entities": 6,
            "top_k_relations": 8,
            "top_k_chunks": 6,
            "min_score": 0.55,
            "token_budget_entities": 450,
            "token_budget_relations": 650,
            "token_budget_chunks": 2400,
            "enable_keyword_extraction": True,
            "vector_relevance_mode": "strict_0_1",
        }
    if mode == "mix":
        return {
            "type": "graph",
            "graph_build_id": graph_build_id,
            "mode": "mix",
            "max_hops": 1,
            "top_k_entities": 6,
            "top_k_relations": 10,
            "top_k_chunks": 8,
            "min_score": 0.50,
            "token_budget_entities": 450,
            "token_budget_relations": 700,
            "token_budget_chunks": 2350,
            "enable_keyword_extraction": True,
            "vector_relevance_mode": "strict_0_1",
        }
    if mode == "global":
        return {
            "type": "graph",
            "graph_build_id": graph_build_id,
            "mode": "global",
            "max_hops": 1,
            "top_k_entities": 8,
            "top_k_relations": 12,
            "top_k_chunks": 6,
            "min_score": 0.45,
            "token_budget_entities": 600,
            "token_budget_relations": 1200,
            "token_budget_chunks": 1700,
            "enable_keyword_extraction": True,
            "vector_relevance_mode": "strict_0_1",
        }
    return {
        "type": "graph",
        "graph_build_id": graph_build_id,
        "mode": "hybrid",
        "max_hops": 1,
        "top_k_entities": 8,
        "top_k_relations": 10,
        "top_k_chunks": 7,
        "min_score": 0.50,
        "token_budget_entities": 550,
        "token_budget_relations": 900,
        "token_budget_chunks": 2000,
        "enable_keyword_extraction": True,
        "vector_relevance_mode": "strict_0_1",
    }


def _wait_for_job(api, job_id: str) -> dict:
    started = time.monotonic()
    while True:
        job = api.get_job(job_id)
        status = job.get("status")
        if status == "succeeded":
            return job
        if status == "failed":
            raise ApiClientError(
                f"Graph job failed: {job_id}",
                payload={"detail": {"code": "graph_job_failed", "message": job.get("error_message") or "unknown error"}},
            )
        if GRAPH_MAX_WAIT_SECONDS is not None and (time.monotonic() - started) > GRAPH_MAX_WAIT_SECONDS:
            raise ApiClientError(
                f"Graph job timed out: {job_id}",
                payload={
                    "detail": {
                        "code": "graph_job_timeout",
                        "message": f"Job did not finish within {GRAPH_MAX_WAIT_SECONDS:.0f} seconds",
                    }
                },
            )
        time.sleep(GRAPH_POLL_INTERVAL_SECONDS)


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "05-docx-graph", "title": "DOCX graph workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("05-docx-graph"), description=artifacts["title"])
        artifacts["project_id"] = project["project_id"]
        print_kv("Project created", {"project_id": artifacts["project_id"]})
        section += 1

        print_section(section, "Ingest source document")
        upload = api.upload_document(
            artifacts["project_id"],
            docs_path("Параметризованные задачи.docx"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        artifacts["document_id"] = upload["document"]["document_id"]
        artifacts["document_version_id"] = upload["document_version"]["version_id"]
        print_kv(
            "Document uploaded",
            {"document_id": artifacts["document_id"], "document_version_id": artifacts["document_version_id"]},
        )
        section += 1

        print_section(section, "Load documents (docx loader)")
        loaded = api.load_documents(artifacts["document_version_id"], loader_type="docx", loader_params={})
        artifacts["document_set_version_id"] = loaded["document_set"]["document_set_version_id"]
        print_kv(
            "Documents loaded",
            {"document_set_version_id": artifacts["document_set_version_id"], "items": len(loaded["items"])},
        )
        section += 1

        print_section(section, "Create segments (regex hierarchy)")
        seg = api.create_segments(
            artifacts["document_set_version_id"],
            split_strategy="regex_hierarchy",
            splitter_params={
                "patterns": [
                    [1, r"^\s*#\s+(.+)$"],
                    [2, r"^\s*##\s+(.+)$"],
                    [3, r"^\s*###\s+(.+)$"],
                    [4, r"^\s*####\s+(.+)$"],
                ],
                "exclude_patterns": [r"^\s*$"],
                "include_parent_content": False,
            },
        )
        artifacts["segment_set_version_id"] = seg["segment_set"]["segment_set_version_id"]
        print_kv(
            "Segments created",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "items": len(seg["items"])},
        )
        section += 1

        print_section(section, "Create chunks (recursive for index)")
        chunk = api.split_segment_set(
            artifacts["segment_set_version_id"],
            strategy="recursive",
            splitter_params={
                "chunk_size": 900,
                "chunk_overlap": 120,
                "length_mode": "string_len",
            },
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
            "05_docx_graph",
            provider="chroma",
            config={"embedding_provider": "openai", "embedding_model_name": "text-embedding-3-small"},
        )
        artifacts["index_id"] = idx["index_id"]
        build = api.create_index_build(artifacts["index_id"], artifacts["source_set_id"], execution_mode="sync")
        artifacts["index_build_id"] = build["build"]["build_id"]
        print_kv(
            "Index build completed",
            {"index_id": artifacts["index_id"], "index_build_id": artifacts["index_build_id"]},
        )
        section += 1

        print_section(section, "Create graph build (async)")
        gb = api.create_graph_build(
            artifacts["project_id"],
            source_type="segment_set",
            source_id=artifacts["segment_set_version_id"],
            backend="networkx",
            execution_mode="async",
            params={
                "extract_entities": True,
                "llm_provider": "openai",
                "llm_model": "gpt-4.1-nano",
                "llm_temperature": 0,
                "index_build_id": artifacts["index_build_id"],
            },
        )
        artifacts["graph_job_id"] = gb.get("job_id")
        artifacts["graph_build_id"] = gb["build"]["graph_build_id"]
        print_kv("Graph build queued", {"graph_build_id": artifacts["graph_build_id"], "graph_job_id": artifacts["graph_job_id"]})
        if artifacts["graph_job_id"]:
            _wait_for_job(api, artifacts["graph_job_id"])
        print_kv("Graph build completed", {"graph_build_id": artifacts["graph_build_id"]})
        section += 1

        run_ids = []
        queries = ["Теория вероятности", "вероятность"]
        for mode in ["local", "mix", "global", "hybrid"]:
            for query in queries:
                print_section(section, f"Retrieve (graph {mode})")
                retrieval = api.retrieve(
                    artifacts["project_id"],
                    {
                        "query": query,
                        "target": "segment_set",
                        "target_id": artifacts["source_set_id"],
                        "strategy": _graph_strategy(artifacts["graph_build_id"], mode),
                        "persist": True,
                    },
                )
                run_ids.append(retrieval.get("run_id"))
                print_kv("Retrieved", {"mode": mode, "query": query, "total": retrieval["total"], "run_id": retrieval.get("run_id")})
                section += 1

        artifacts["retrieval_run_ids"] = run_ids
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
