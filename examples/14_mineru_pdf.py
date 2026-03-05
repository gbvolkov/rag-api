import os

from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


PDF_MIME = "application/pdf"
PDF_FILE = "statement.pdf"
QUERY = "statement date"
INDEX_CONFIG = {"embedding_provider": "openai", "embedding_model_name": "text-embedding-3-small"}
RECURSIVE_SPLITTER_PARAMS = {"chunk_size": 1200, "chunk_overlap": 120}


def _mineru_loader_params() -> dict:
    start_page = int(os.getenv("MINERU_START_PAGE", "0"))
    end_page = int(os.getenv("MINERU_END_PAGE", "4"))
    return {
        "parse_mode": "txt",
        "timeout_seconds": 1200,
        "start_page": start_page,
        "end_page": end_page,
        "parse_formula": False,
        "parse_table": False,
    }


def _segment_preview(segment_items: list[dict]) -> dict:
    if not segment_items:
        return {"items": 0}

    first = segment_items[0]
    metadata = first.get("metadata") or {}
    return {
        "items": len(segment_items),
        "sample_source": metadata.get("source", "n/a"),
        "content_preview": (first.get("content") or "")[:120],
    }


def _retrieval_preview(retrieval: dict) -> dict:
    return {"total": retrieval["total"], "run_id": retrieval.get("run_id")}


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "14-mineru-pdf", "title": "MinerU PDF workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("14-mineru-pdf"), description=artifacts["title"])
        project_id = project["project_id"]
        artifacts["project_id"] = project_id
        print_kv("Project created", {"project_id": project_id})
        section += 1

        print_section(section, "Ingest source document")
        source_path = docs_path(PDF_FILE)
        upload = api.upload_document(project_id, source_path, PDF_MIME)
        document_id = upload["document"]["document_id"]
        document_version_id = upload["document_version"]["version_id"]
        artifacts["document_id"] = document_id
        artifacts["document_version_id"] = document_version_id
        print_kv(
            "Document uploaded",
            {"filename": source_path.name, "document_id": document_id, "document_version_id": document_version_id},
        )
        section += 1

        print_section(section, "Load documents (miner_u)")
        mineru_params = _mineru_loader_params()
        loaded = api.load_documents(document_version_id, loader_type="miner_u", loader_params=mineru_params)
        document_set_version_id = loaded["document_set"]["document_set_version_id"]
        artifacts["document_set_version_id"] = document_set_version_id
        print_kv(
            "Documents loaded",
            {
                "document_set_version_id": document_set_version_id,
                "items": len(loaded["items"]),
                "start_page": mineru_params["start_page"],
                "end_page": mineru_params["end_page"],
            },
        )
        section += 1

        print_section(section, "Create segments (recursive)")
        seg = api.create_segments(
            document_set_version_id,
            split_strategy="recursive",
            splitter_params=RECURSIVE_SPLITTER_PARAMS,
        )
        segment_set_version_id = seg["segment_set"]["segment_set_version_id"]
        artifacts["segment_set_version_id"] = segment_set_version_id
        artifacts["source_set_id"] = segment_set_version_id
        print_kv("Segments created", {"segment_set_version_id": segment_set_version_id, **_segment_preview(seg["items"])})
        section += 1

        print_section(section, "Create index and build")
        idx = api.create_index(project_id, "14_mineru_pdf", provider="chroma", config=INDEX_CONFIG)
        index_id = idx["index_id"]
        build = api.create_index_build(index_id, segment_set_version_id, execution_mode="sync")
        index_build_id = build["build"]["build_id"]
        artifacts["index_id"] = index_id
        artifacts["index_build_id"] = index_build_id
        print_kv("Index build completed", {"index_id": index_id, "index_build_id": index_build_id})
        section += 1

        print_section(section, "Retrieve (vector)")
        retrieval = api.retrieve(
            project_id,
            {
                "query": QUERY,
                "target": "index_build",
                "target_id": index_build_id,
                "strategy": {"type": "vector", "k": 3},
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
