from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "13-dual-storage", "title": "Dual storage workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("13-dual-storage"), description=artifacts["title"])
        artifacts["project_id"] = project["project_id"]
        print_kv("Project created", {"project_id": artifacts["project_id"]})
        section += 1

        print_section(section, "Ingest source document")
        upload = api.upload_document(artifacts["project_id"], docs_path("dual_storage_demo.txt"), "text/plain")
        artifacts["document_id"] = upload["document"]["document_id"]
        artifacts["document_version_id"] = upload["document_version"]["version_id"]
        print_kv(
            "Document uploaded",
            {"document_id": artifacts["document_id"], "document_version_id": artifacts["document_version_id"]},
        )
        section += 1

        print_section(section, "Load documents (text loader)")
        loaded = api.load_documents(
            artifacts["document_version_id"],
            loader_type="text",
            loader_params={},
        )
        artifacts["document_set_version_id"] = loaded["document_set"]["document_set_version_id"]
        print_kv(
            "Documents loaded",
            {"document_set_version_id": artifacts["document_set_version_id"], "items": len(loaded["items"])},
        )
        section += 1

        print_section(section, "Create segments")
        seg = api.create_segments(
            artifacts["document_set_version_id"],
            split_strategy="identity",
        )
        artifacts["segment_set_version_id"] = seg["segment_set"]["segment_set_version_id"]
        print_kv(
            "Segments created",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "items": len(seg["items"])},
        )
        section += 1

        print_section(section, "Create parent chunks (regex)")
        parent_chunks = api.split_segment_set(
            artifacts["segment_set_version_id"],
            strategy="regex",
            splitter_params={
                "pattern": r"(?=Dual storage keeps compact searchable chunks in a vector index while storing)",
            },
        )
        artifacts["parent_source_set_id"] = parent_chunks["segment_set"]["segment_set_version_id"]
        print_kv(
            "Parent chunks created",
            {"source_set_id": artifacts["parent_source_set_id"], "items": len(parent_chunks["items"])},
        )
        section += 1

        print_section(section, "Create child chunks (token)")
        chunk = api.split_segment_set(
            artifacts["parent_source_set_id"],
            strategy="token",
            splitter_params={"chunk_size": 35, "chunk_overlap": 8, "model_name": "cl100k_base"},
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
            "13_dual_storage",
            provider="chroma",
            config={"embedding_provider": "openai", "embedding_model_name": "text-embedding-3-small"},
        )
        artifacts["index_id"] = idx["index_id"]
        build = api.create_index_build(
            artifacts["index_id"],
            artifacts["source_set_id"],
            execution_mode="sync",
            parent_set_id=artifacts["parent_source_set_id"],
            id_key="source_segment_item_id",
            doc_store={"backend": "local_file"},
        )
        artifacts["index_build_id"] = build["build"]["build_id"]
        print_kv(
            "Index build completed",
            {"index_id": artifacts["index_id"], "index_build_id": artifacts["index_build_id"]},
        )
        section += 1

        print_section(section, "Retrieve (dual storage)")
        retrieval = api.retrieve(
            artifacts["project_id"],
            {
                "query": "What is retrieval augmented generation and why use it?",
                "target": "index_build",
                "target_id": artifacts["index_build_id"],
                "strategy": {
                    "type": "dual_storage",
                    "vector_search": {"k": 5},
                    "search_kwargs": {"k": 5},
                    "id_key": "source_segment_item_id",
                    "search_type": "similarity_score_threshold",
                    "score_threshold": 0.0,
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
