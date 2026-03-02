from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


def run_example(client=None):
    api = client or default_client()
    artifacts = {
        "example_id": "02-markdown-enrichment-vector",
        "title": "Markdown enrichment + vector workflow",
        "status": "ok",
    }
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("02-markdown-enrichment-vector"), description=artifacts["title"])
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

        print_section(section, "Create segments")
        seg = api.create_segments(artifacts["document_version_id"], loader_type="text", loader_params={})
        artifacts["segment_set_version_id"] = seg["segment_set"]["segment_set_version_id"]
        print_kv(
            "Segments created",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "items": len(seg["items"])},
        )
        section += 1

        print_section(section, "Create chunks (recursive)")
        chunk = api.create_chunks(
            artifacts["segment_set_version_id"],
            strategy="recursive",
            chunker_params={"chunk_size": 1000, "chunk_overlap": 100},
        )
        artifacts["chunk_set_version_id"] = chunk["chunk_set"]["chunk_set_version_id"]
        print_kv(
            "Chunks created",
            {"chunk_set_version_id": artifacts["chunk_set_version_id"], "items": len(chunk["items"])},
        )
        section += 1

        print_section(section, "Run enrichment")
        enr = api.run_enrich(
            artifacts["segment_set_version_id"],
            {"execution_mode": "sync", "llm_provider": "openai", "llm_model": "gpt-4.1-nano"},
        )
        artifacts["segment_set_version_id"] = enr["segment_set"]["segment_set_version_id"]
        print_kv("Enrichment completed", {"segment_set_version_id": artifacts["segment_set_version_id"]})
        section += 1

        print_section(section, "Create index and build")
        idx = api.create_index(
            artifacts["project_id"],
            "02-markdown-enrichment-vector-idx",
            provider="faiss",
            config={"embedding_provider": "openai"},
        )
        artifacts["index_id"] = idx["index_id"]
        build = api.create_index_build(artifacts["index_id"], artifacts["chunk_set_version_id"], execution_mode="sync")
        artifacts["index_build_id"] = build["build"]["build_id"]
        print_kv(
            "Index build completed",
            {"index_id": artifacts["index_id"], "index_build_id": artifacts["index_build_id"]},
        )
        section += 1

        print_section(section, "Retrieve (vector)")
        retrieval = api.retrieve(
            artifacts["project_id"],
            {
                "query": "einstein quotes",
                "target": "index_build",
                "target_id": artifacts["index_build_id"],
                "strategy": {"type": "vector", "k": 2},
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
