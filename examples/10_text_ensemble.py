from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


TEXT_MIME = "text/plain"
TEXT_FILE = "terms&defs.txt"
QUERY = "Cost of risk"
INDEX_CONFIG = {"embedding_provider": "openai", "embedding_model_name": "text-embedding-3-small"}
SENTENCE_SPLITTER_PARAMS = {"chunk_size": 300, "chunk_overlap": 30, "language": "auto"}
ENSEMBLE_STRATEGY = {
    "type": "ensemble",
    "sources": [{"type": "bm25", "k": 3}, {"type": "vector", "k": 3}],
    "weights": [0.5, 0.5],
}


def _segment_preview(segment_items: list[dict]) -> dict:
    if not segment_items:
        return {"items": 0}

    first = segment_items[0]
    metadata = first.get("metadata") or {}
    return {
        "items": len(segment_items),
        "sample_chunk_index": metadata.get("chunk_index", "n/a"),
        "content_preview": (first.get("content") or "")[:120],
    }


def _retrieval_preview(retrieval: dict) -> dict:
    return {"total": retrieval["total"], "run_id": retrieval.get("run_id")}


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "10-text-ensemble", "title": "Text ensemble workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("10-text-ensemble"), description=artifacts["title"])
        project_id = project["project_id"]
        artifacts["project_id"] = project_id
        print_kv("Project created", {"project_id": project_id})
        section += 1

        print_section(section, "Ingest source document")
        source_path = docs_path(TEXT_FILE)
        upload = api.upload_document(project_id, source_path, TEXT_MIME)
        document_id = upload["document"]["document_id"]
        document_version_id = upload["document_version"]["version_id"]
        artifacts["document_id"] = document_id
        artifacts["document_version_id"] = document_version_id
        print_kv(
            "Document uploaded",
            {"filename": source_path.name, "document_id": document_id, "document_version_id": document_version_id},
        )
        section += 1

        print_section(section, "Load documents (text loader)")
        loaded = api.load_documents(document_version_id, loader_type="text", loader_params={})
        document_set_version_id = loaded["document_set"]["document_set_version_id"]
        artifacts["document_set_version_id"] = document_set_version_id
        print_kv("Documents loaded", {"document_set_version_id": document_set_version_id, "items": len(loaded["items"])})
        section += 1

        print_section(section, "Create segments (sentence)")
        seg = api.create_segments(
            document_set_version_id,
            split_strategy="sentence",
            splitter_params=SENTENCE_SPLITTER_PARAMS,
        )
        segment_set_version_id = seg["segment_set"]["segment_set_version_id"]
        artifacts["segment_set_version_id"] = segment_set_version_id
        artifacts["source_set_id"] = segment_set_version_id
        print_kv("Segments created", {"segment_set_version_id": segment_set_version_id, **_segment_preview(seg["items"])})
        section += 1

        print_section(section, "Create index and build")
        idx = api.create_index(project_id, "10_text_ensemble", provider="chroma", config=INDEX_CONFIG)
        index_id = idx["index_id"]
        build = api.create_index_build(index_id, segment_set_version_id, execution_mode="sync")
        index_build_id = build["build"]["build_id"]
        artifacts["index_id"] = index_id
        artifacts["index_build_id"] = index_build_id
        print_kv("Index build completed", {"index_id": index_id, "index_build_id": index_build_id})
        section += 1

        run_ids: list[str | None] = []

        print_section(section, "Retrieve (bm25)")
        bm25 = api.retrieve(
            project_id,
            {
                "query": QUERY,
                "target": "segment_set",
                "target_id": segment_set_version_id,
                "strategy": {"type": "bm25", "k": 3},
                "persist": True,
            },
        )
        run_ids.append(bm25.get("run_id"))
        print_kv("Retrieved", {"query": QUERY, **_retrieval_preview(bm25)})
        section += 1

        print_section(section, "Retrieve (vector)")
        vector = api.retrieve(
            project_id,
            {
                "query": QUERY,
                "target": "index_build",
                "target_id": index_build_id,
                "strategy": {"type": "vector", "k": 3},
                "persist": True,
            },
        )
        run_ids.append(vector.get("run_id"))
        print_kv("Retrieved", {"query": QUERY, **_retrieval_preview(vector)})
        section += 1

        print_section(section, "Retrieve (ensemble)")
        ensemble = api.retrieve(
            project_id,
            {
                "query": QUERY,
                "target": "index_build",
                "target_id": index_build_id,
                "strategy": ENSEMBLE_STRATEGY,
                "persist": True,
            },
        )
        run_ids.append(ensemble.get("run_id"))
        artifacts["retrieval_run_ids"] = run_ids
        print_kv("Retrieved", {"query": QUERY, **_retrieval_preview(ensemble)})
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
