from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


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
        if not docs_path(pdf_file).exists():
            pdf_file = "statement.pdf"

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

        print_section(section, "Create segments")
        seg = api.create_segments(
            artifacts["document_version_id"],
            loader_type="pdf",
            loader_params={"parse_mode": "text"},
        )
        artifacts["segment_set_version_id"] = seg["segment_set"]["segment_set_version_id"]
        print_kv(
            "Segments created",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "items": len(seg["items"])},
        )
        section += 1

        print_section(section, "Run RAPTOR")
        rap = api.run_raptor(
            artifacts["segment_set_version_id"],
            {
                "execution_mode": "sync",
                "max_levels": 3,
                "llm_provider": "openai",
                "llm_model": "gpt-4.1-nano",
                "llm_temperature": 0,
                "embedding_provider": "openai",
            },
        )
        artifacts["segment_set_version_id"] = rap["segment_set"]["segment_set_version_id"]
        runs = api.list_raptor_runs(artifacts["project_id"])
        artifacts["raptor_run_id"] = runs[0]["raptor_run_id"] if runs else None
        print_kv(
            "RAPTOR completed",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "raptor_runs": len(runs)},
        )
        section += 1

        print_section(section, "Create chunks")
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
        if "statement" in pdf_file.lower():
            query = "balance summary"

        print_section(section, "Retrieve (dual storage)")
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
