import re
from pathlib import Path
from typing import Any

from examples.api_client import ApiClientError
from examples.example_utils import (
    default_client,
    docs_first,
    docs_path,
    export_results_json,
    print_api_error,
    print_kv,
    print_section,
    project_name,
)


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
VECTOR_STRATEGY = {"type": "vector", "k": 5}
EMBEDDING_CONFIG = {"embedding_provider": "openai", "embedding_model_name": "text-embedding-3-small"}
PREFERRED_DOCX = "KP_IT_IB_Strategy_Recalc_v7_AppC.docx"
QUERIES = [
    "Состав работ",
    "Команда",
    "трудозатраты",
    "этапы работ",
    "Стоимость",
    "Цель проекта",
]

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


def _resolve_docx_file() -> Path:
    preferred = docs_path(PREFERRED_DOCX)
    if preferred.exists():
        return preferred
    return docs_first("*.docx")


def _query_pattern(query: str) -> str:
    return re.sub(r"\\\s+", r"\\s+", re.escape(query.strip()))


def _retrieve_and_log(
    api: Any,
    project_id: str,
    *,
    query: str,
    target: str,
    target_id: str,
    strategy: dict[str, Any],
    section: int,
) -> str | None:
    strategy_type = strategy.get("type", "unknown")
    print_section(section, f"Retrieve ({strategy_type})")
    result = api.retrieve(
        project_id,
        {
            "query": query,
            "target": target,
            "target_id": target_id,
            "strategy": strategy,
            "persist": True,
        },
    )
    run_id = result.get("run_id")
    print_kv("Retrieved", {"query": query, "total": result["total"], "run_id": run_id})
    return run_id


def run_example(client=None):
    api = client or default_client()
    artifacts = {"example_id": "06-docx-regex", "title": "DOCX regex workflow", "status": "ok"}
    section = 1
    try:
        print_section(section, "Create project")
        project = api.create_project(project_name("06-docx-regex"), description=artifacts["title"])
        project_id = project["project_id"]
        artifacts["project_id"] = project_id
        print_kv("Project created", {"project_id": project_id})
        section += 1

        print_section(section, "Ingest source document")
        source_docx = _resolve_docx_file()
        upload = api.upload_document(project_id, source_docx, DOCX_MIME)
        document_id = upload["document"]["document_id"]
        document_version_id = upload["document_version"]["version_id"]
        artifacts["document_id"] = document_id
        artifacts["document_version_id"] = document_version_id
        print_kv(
            "Document uploaded",
            {"filename": source_docx.name, "document_id": document_id, "document_version_id": document_version_id},
        )
        section += 1

        print_section(section, "Load documents (docx loader)")
        loaded = api.load_documents(document_version_id, loader_type="docx", loader_params={})
        document_set_version_id = loaded["document_set"]["document_set_version_id"]
        artifacts["document_set_version_id"] = document_set_version_id
        print_kv("Documents loaded", {"document_set_version_id": document_set_version_id, "items": len(loaded["items"])})
        section += 1

        print_section(section, "Create segments (regex)")
        seg = api.create_segments(
            document_set_version_id,
            split_strategy="regex",
            splitter_params={"pattern": REGEX_PATTERN, "chunk_size": 1200, "chunk_overlap": 0},
        )
        segment_set_version_id = seg["segment_set"]["segment_set_version_id"]
        artifacts["segment_set_version_id"] = segment_set_version_id
        print_kv("Segments created", {"segment_set_version_id": segment_set_version_id, "items": len(seg["items"])})
        section += 1

        # Keep source_set_id artifact for compatibility with existing result processing.
        source_set_id = segment_set_version_id
        artifacts["source_set_id"] = source_set_id

        run_ids: list[str | None] = []
        for query in QUERIES:
            run_id = _retrieve_and_log(
                api,
                project_id,
                query=query,
                target="segment_set",
                target_id=source_set_id,
                strategy={"type": "regex", "pattern": _query_pattern(query)},
                section=section,
            )
            run_ids.append(run_id)
            section += 1

        print_section(section, "Create index and build")
        idx = api.create_index(project_id, "06_docx_regex", provider="chroma", config=EMBEDDING_CONFIG)
        index_id = idx["index_id"]
        build = api.create_index_build(index_id, source_set_id, execution_mode="sync")
        index_build_id = build["build"]["build_id"]
        artifacts["index_id"] = index_id
        artifacts["index_build_id"] = index_build_id
        print_kv("Index build completed", {"index_id": index_id, "index_build_id": index_build_id})
        section += 1

        for query in QUERIES:
            run_id = _retrieve_and_log(
                api,
                project_id,
                query=query,
                target="index_build",
                target_id=index_build_id,
                strategy=VECTOR_STRATEGY,
                section=section,
            )
            run_ids.append(run_id)
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
