from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


HTML_MIME = "text/html"
HTML_FILE = "15_test.html"
QUERY = "Which project belongs to A. Novak and what stage is it in?"
INDEX_CONFIG = {"embedding_provider": "openai", "embedding_model_name": "text-embedding-3-small"}
HTML_PARENT_SPLITTER_PARAMS = {
    "output_format": "markdown",
    "split_table_rows": True,
    "max_rows_per_chunk": 6,
    "use_first_row_as_header": True,
    "include_parent_content": False,
}
CHILD_RECURSIVE_SPLITTER_PARAMS = {"chunk_size": 1000, "chunk_overlap": 120}
DUAL_STORAGE_STRATEGY = {
    "type": "dual_storage",
    "vector_search": {"k": 6},
    "search_kwargs": {"k": 6},
    "id_key": "source_segment_item_id",
    "search_type": "similarity_score_threshold",
    "score_threshold": 0.0,
}


def _segment_preview(segment_items: list[dict]) -> dict:
    if not segment_items:
        return {"items": 0}

    first = segment_items[0]
    metadata = first.get("metadata") or {}
    return {
        "items": len(segment_items),
        "sample_is_table": metadata.get("is_table", "n/a"),
        "content_preview": (first.get("content") or "")[:120],
    }


def _retrieval_preview(retrieval: dict) -> dict:
    return {"total": retrieval["total"], "run_id": retrieval.get("run_id")}


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "16-html-md", "title": "HTML to Markdown dual retrieval workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("16-html-md"), description=artifacts["title"])
        project_id = project["project_id"]
        artifacts["project_id"] = project_id
        print_kv("Project created", {"project_id": project_id})
        section += 1

        print_section(section, "Ingest source document")
        source_path = docs_path(HTML_FILE)
        upload = api.upload_document(project_id, source_path, HTML_MIME)
        document_id = upload["document"]["document_id"]
        document_version_id = upload["document_version"]["version_id"]
        artifacts["document_id"] = document_id
        artifacts["document_version_id"] = document_version_id
        print_kv(
            "Document uploaded",
            {"filename": source_path.name, "document_id": document_id, "document_version_id": document_version_id},
        )
        section += 1

        print_section(section, "Load documents (html loader)")
        loaded = api.load_documents(document_version_id, loader_type="html", loader_params={"output_format": "html"})
        document_set_version_id = loaded["document_set"]["document_set_version_id"]
        artifacts["document_set_version_id"] = document_set_version_id
        print_kv("Documents loaded", {"document_set_version_id": document_set_version_id, "items": len(loaded["items"])})
        section += 1

        print_section(section, "Create parent segments (html -> markdown)")
        parent_seg = api.create_segments(
            document_set_version_id,
            split_strategy="html",
            splitter_params=HTML_PARENT_SPLITTER_PARAMS,
        )
        parent_source_set_id = parent_seg["segment_set"]["segment_set_version_id"]
        artifacts["parent_source_set_id"] = parent_source_set_id
        artifacts["source_set_id"] = parent_source_set_id
        print_kv("Parent segments created", {"source_set_id": parent_source_set_id, **_segment_preview(parent_seg["items"])})
        section += 1

        print_section(section, "Create child segments (recursive)")
        child_seg = api.split_segment_set(
            parent_source_set_id,
            strategy="recursive",
            splitter_params=CHILD_RECURSIVE_SPLITTER_PARAMS,
        )
        child_source_set_id = child_seg["segment_set"]["segment_set_version_id"]
        artifacts["child_source_set_id"] = child_source_set_id
        print_kv("Child segments created", {"source_set_id": child_source_set_id, **_segment_preview(child_seg["items"])})
        section += 1

        print_section(section, "Create index and build")
        idx = api.create_index(project_id, "16_html_md", provider="chroma", config=INDEX_CONFIG)
        index_id = idx["index_id"]
        build = api.create_index_build(
            index_id,
            child_source_set_id,
            execution_mode="sync",
            parent_set_id=parent_source_set_id,
            id_key="source_segment_item_id",
            doc_store={"backend": "local_file"},
        )
        index_build_id = build["build"]["build_id"]
        artifacts["index_id"] = index_id
        artifacts["index_build_id"] = index_build_id
        print_kv("Index build completed", {"index_id": index_id, "index_build_id": index_build_id})
        section += 1

        print_section(section, "Retrieve (dual storage)")
        retrieval = api.retrieve(
            project_id,
            {
                "query": QUERY,
                "target": "index_build",
                "target_id": index_build_id,
                "strategy": DUAL_STORAGE_STRATEGY,
                "persist": True,
            },
        )
        run_id = retrieval.get("run_id")
        artifacts["retrieval_run_ids"] = [run_id]
        print_kv("Retrieved", {"query": QUERY, **_retrieval_preview(retrieval)})
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
