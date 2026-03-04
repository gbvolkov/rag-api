from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name

DOC_PAGE_LIMIT = 10


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "03-pdf-semantic", "title": "PDF semantic workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("03-pdf-semantic"), description=artifacts["title"])
        artifacts["project_id"] = project["project_id"]
        print_kv("Project created", {"project_id": artifacts["project_id"]})
        section += 1

        pdf_file = "2025_soo_frp_russkij-yazyk_10_11-2.pdf"
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

        print_section(section, "Load documents (pymupdf markdown)")
        loaded = api.load_documents(
            artifacts["document_version_id"],
            loader_type="pymupdf",
            loader_params={"output_format": "markdown"},
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
        artifacts["used_loader"] = "pymupdf"
        artifacts["segment_set_version_id"] = seg["segment_set"]["segment_set_version_id"]
        print_kv(
            "Segments created",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "items": len(seg["items"])},
        )
        section += 1

        if DOC_PAGE_LIMIT and len(seg["items"]) > DOC_PAGE_LIMIT:
            artifacts["doc_page_limit"] = DOC_PAGE_LIMIT

        print_section(section, "Create structured chunks (regex_hierarchy)")
        structured = api.split_segment_set(
            artifacts["segment_set_version_id"],
            strategy="regex_hierarchy",
            splitter_params={
                "patterns": [
                    [1, r"^\s*#\s+(.+)$"],
                    [2, r"^\s*##\s+(.+)$"],
                    [3, r"^\s*###\s+(.+)$"],
                    [1, r"^\s*\*\*(.+?)\*\*\s*$"],
                ],
                "exclude_patterns": [r"^\s*\d+\s*$"],
                "include_parent_content": False,
            },
        )
        artifacts["structured_source_set_id"] = structured["segment_set"]["segment_set_version_id"]
        print_kv(
            "Structured chunks created",
            {"source_set_id": artifacts["structured_source_set_id"], "items": len(structured["items"])},
        )
        section += 1

        print_section(section, "Create semantic chunks")
        chunk = api.split_segment_set(
            artifacts["structured_source_set_id"],
            strategy="semantic",
            splitter_params={
                "embedding_provider": "openai",
                "threshold_type": "fixed",
                "threshold": 0.8,
                "window_size": 4,
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
            "03_pdf_semantic",
            provider="chroma",
            config={"embedding_provider": "openai", "collection_name": "03_pdf_semantic"},
        )
        artifacts["index_id"] = idx["index_id"]
        build = api.create_index_build(artifacts["index_id"], artifacts["source_set_id"], execution_mode="sync")
        artifacts["index_build_id"] = build["build"]["build_id"]
        print_kv(
            "Index build completed",
            {"index_id": artifacts["index_id"], "index_build_id": artifacts["index_build_id"]},
        )
        section += 1

        query = "Что такое морфология?"
        if "statement" in pdf_file.lower():
            query = "balance summary"

        run_ids = []
        print_section(section, "Retrieve (vector)") 
        vec = api.retrieve(
            artifacts["project_id"],
            {
                "query": query,
                "target": "index_build",
                "target_id": artifacts["index_build_id"],
                "strategy": {"type": "vector", "k": 10},
                "persist": True,
            },
        )
        run_ids.append(vec.get("run_id"))
        print_kv("Retrieved", {"total": vec["total"], "run_id": vec.get("run_id")})
        section += 1

        print_section(section, "Retrieve (rerank)")
        rerank = api.retrieve(
            artifacts["project_id"],
            {
                "query": query,
                "target": "index_build",
                "target_id": artifacts["index_build_id"],
                "strategy": {
                    "type": "rerank",
                    "base": {"type": "vector", "k": 10},
                    "model_name": "BAAI/bge-reranker-v2-m3",
                    "top_k": 3,
                    "max_score_ratio": 0.08,
                    "device": "cpu",
                }, 
                "persist": True,
            },
        )
        run_ids.append(rerank.get("run_id"))
        artifacts["retrieval_run_ids"] = run_ids
        print_kv("Retrieved", {"total": rerank["total"], "run_id": rerank.get("run_id")})
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
