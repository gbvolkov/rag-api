from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "10-text-ensemble", "title": "Text ensemble workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("10-text-ensemble"), description=artifacts["title"])
        artifacts["project_id"] = project["project_id"]
        print_kv("Project created", {"project_id": artifacts["project_id"]})
        section += 1

        print_section(section, "Ingest source document")
        upload = api.upload_document(artifacts["project_id"], docs_path("terms&defs.txt"), "text/plain")
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

        print_section(section, "Create chunks (sentence)")
        chunk = api.create_chunks(
            artifacts["segment_set_version_id"],
            strategy="sentence",
            chunker_params={"chunk_size": 300, "chunk_overlap": 30, "language": "auto"},
        )
        artifacts["chunk_set_version_id"] = chunk["chunk_set"]["chunk_set_version_id"]
        print_kv(
            "Chunks created",
            {"chunk_set_version_id": artifacts["chunk_set_version_id"], "items": len(chunk["items"])},
        )
        section += 1

        print_section(section, "Create index and build")
        idx = api.create_index(
            artifacts["project_id"],
            "10_text_ensemble",
            provider="chroma",
            config={"embedding_provider": "openai", "embedding_model_name": "text-embedding-3-small"},
        )
        artifacts["index_id"] = idx["index_id"]
        build = api.create_index_build(artifacts["index_id"], artifacts["chunk_set_version_id"], execution_mode="sync")
        artifacts["index_build_id"] = build["build"]["build_id"]
        print_kv(
            "Index build completed",
            {"index_id": artifacts["index_id"], "index_build_id": artifacts["index_build_id"]},
        )
        section += 1

        query = "Cost of risk"
        run_ids: list[str | None] = []

        print_section(section, "Retrieve (bm25)")
        bm25 = api.retrieve(
            artifacts["project_id"],
            {
                "query": query,
                "target": "chunk_set",
                "target_id": artifacts["chunk_set_version_id"],
                "strategy": {"type": "bm25", "k": 3},
                "persist": True,
            },
        )
        run_ids.append(bm25.get("run_id"))
        print_kv("Retrieved", {"total": bm25["total"], "run_id": bm25.get("run_id")})
        section += 1

        print_section(section, "Retrieve (vector)")
        vector = api.retrieve(
            artifacts["project_id"],
            {
                "query": query,
                "target": "index_build",
                "target_id": artifacts["index_build_id"],
                "strategy": {"type": "vector", "k": 3},
                "persist": True,
            },
        )
        run_ids.append(vector.get("run_id"))
        print_kv("Retrieved", {"total": vector["total"], "run_id": vector.get("run_id")})
        section += 1

        print_section(section, "Retrieve (ensemble)")
        ensemble = api.retrieve(
            artifacts["project_id"],
            {
                "query": query,
                "target": "index_build",
                "target_id": artifacts["index_build_id"],
                "strategy": {
                    "type": "ensemble",
                    "sources": [{"type": "bm25", "k": 3}, {"type": "vector", "k": 3}],
                    "weights": [0.5, 0.5],
                },
                "persist": True,
            },
        )
        run_ids.append(ensemble.get("run_id"))
        artifacts["retrieval_run_ids"] = run_ids
        print_kv("Retrieved", {"total": ensemble["total"], "run_id": ensemble.get("run_id")})
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
