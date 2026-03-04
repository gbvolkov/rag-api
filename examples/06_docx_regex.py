import re

from examples.api_client import ApiClientError
from examples.example_utils import default_client, docs_path, export_results_json, print_api_error, print_kv, print_section, project_name


REGEX_PATTERN = (
    r"(?m)(?=^(?:"
    r"#\s+\d+\.\s+.+|"
    r"##\s+\d+\.\d+\.\s+.+|"
    r"###\s+Этап\s+(?:Э\d+|PA)\.\s+.+|"
    r"\*\*(?:D\d+-\d+|PA-\d+)\.\s+.+\*\*|"
    r"-\s+(?:D\d+-\d+|PA-\d+)\.\s+.+|"
    r"\|\s*(?:D\d+-\d+|PA-\d+)\s*\|"
    r"))"
)


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "06-docx-regex", "title": "DOCX regex workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("06-docx-regex"), description=artifacts["title"])
        artifacts["project_id"] = project["project_id"]
        print_kv("Project created", {"project_id": artifacts["project_id"]})
        section += 1

        print_section(section, "Ingest source document")
        upload = api.upload_document(
            artifacts["project_id"],
            docs_path("KP_IT_IB_Strategy_Recalc_v7_AppC.docx"),
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

        print_section(section, "Create segments")
        seg = api.create_segments(artifacts["document_set_version_id"], split_strategy="identity")
        artifacts["segment_set_version_id"] = seg["segment_set"]["segment_set_version_id"]
        print_kv(
            "Segments created",
            {"segment_set_version_id": artifacts["segment_set_version_id"], "items": len(seg["items"])},
        )
        section += 1

        print_section(section, "Create chunks (regex)")
        chunk = api.split_segment_set(
            artifacts["segment_set_version_id"],
            strategy="regex",
            splitter_params={"pattern": REGEX_PATTERN, "chunk_size": 1200, "chunk_overlap": 0},
        )
        artifacts["source_set_id"] = chunk["segment_set"]["segment_set_version_id"]
        print_kv(
            "Chunks created",
            {"source_set_id": artifacts["source_set_id"], "items": len(chunk["items"])},
        )
        section += 1

        queries = ["Состав работ", "Команда", "трудозатраты", "этапы работ", "Стоимость", "Цель проекта"]
        run_ids: list[str | None] = []
        for query in queries:
            query_pattern = re.sub(r"\\\s+", r"\\s+", re.escape(query.strip()))
            print_section(section, "Retrieve (regex)")
            regex_result = api.retrieve(
                artifacts["project_id"],
                {
                    "query": query,
                    "target": "segment_set",
                    "target_id": artifacts["source_set_id"],
                    "strategy": {"type": "regex", "pattern": query_pattern},
                    "persist": True,
                },
            )
            run_ids.append(regex_result.get("run_id"))
            print_kv("Retrieved", {"query": query, "total": regex_result["total"], "run_id": regex_result.get("run_id")})
            section += 1

        print_section(section, "Create index and build")
        idx = api.create_index(
            artifacts["project_id"],
            "06_docx_regex",
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

        for query in queries:
            print_section(section, "Retrieve (vector)")
            vector_result = api.retrieve(
                artifacts["project_id"],
                {
                    "query": query,
                    "target": "index_build",
                    "target_id": artifacts["index_build_id"],
                    "strategy": {"type": "vector", "k": 5},
                    "persist": True,
                },
            )
            run_ids.append(vector_result.get("run_id"))
            print_kv("Retrieved", {"query": query, "total": vector_result["total"], "run_id": vector_result.get("run_id")})
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
