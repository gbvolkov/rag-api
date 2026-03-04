import json
from importlib import metadata
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_rag_lib_producer_version() -> str:
    try:
        dist = metadata.distribution("rag-lib")
    except metadata.PackageNotFoundError:
        return "unknown"

    direct_url = dist.read_text("direct_url.json")
    if direct_url:
        try:
            payload = json.loads(direct_url)
            commit_id = payload.get("vcs_info", {}).get("commit_id")
            if commit_id:
                return str(commit_id)
        except json.JSONDecodeError:
            pass

    return dist.version or "unknown"


def _default_loader_policy_mime_class_map() -> dict[str, str]:
    return {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word",
        "text/html": "html",
        "application/xhtml+xml": "html",
        "text/csv": "csv",
        "application/csv": "csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
        "application/json": "json",
        "text/json": "json",
        "text/plain": "text",
        "text/markdown": "text",
    }


def _default_loader_policy_extension_class_map() -> dict[str, str]:
    return {
        ".pdf": "pdf",
        ".docx": "word",
        ".html": "html",
        ".htm": "html",
        ".xhtml": "html",
        ".csv": "csv",
        ".xlsx": "excel",
        ".json": "json",
        ".txt": "text",
        ".md": "text",
        ".log": "text",
    }


def _default_loader_policy_class_rules() -> dict[str, dict[str, Any]]:
    return {
        "pdf": {
            "default_loader": "pdf",
            "allowed_loaders": ["pdf", "miner_u", "pymupdf", "text", "regex"],
        },
        "word": {
            "default_loader": "docx",
            "allowed_loaders": ["docx", "text", "regex"],
        },
        "html": {
            "default_loader": "html",
            "allowed_loaders": ["html", "text", "regex"],
        },
        "csv": {
            "default_loader": "csv",
            "allowed_loaders": ["csv", "text", "table", "regex"],
        },
        "excel": {
            "default_loader": "excel",
            "allowed_loaders": ["excel", "text", "table", "regex"],
        },
        "json": {
            "default_loader": "json",
            "allowed_loaders": ["json", "text", "regex"],
        },
        "text": {
            "default_loader": "text",
            "allowed_loaders": ["text", "regex", "table"],
        },
        "web": {
            "default_loader": "web",
            "allowed_loaders": ["web", "web_async"],
        },
    }


def _default_loader_policy_loader_defaults() -> dict[str, dict[str, Any]]:
    return {
        "pdf": {"parse_mode": "text"},
        "miner_u": {"parse_mode": "auto"},
        "pymupdf": {"output_format": "markdown"},
        "docx": {},
        "html": {"output_format": "markdown"},
        "csv": {"output_format": "markdown"},
        "excel": {"output_format": "markdown"},
        "json": {
            "output_format": "json",
            "schema": ".",
            "schema_dialect": "dot_path",
            "ensure_ascii": False,
        },
        "text": {},
        "table": {},
        "regex": {},
        "web": {"depth": 0, "output_format": "markdown", "fetch_mode": "requests"},
        "web_async": {"depth": 0, "output_format": "markdown", "fetch_mode": "requests", "max_concurrency": 5},
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "RAG API"
    api_v1_str: str = "/api/v1"
    environment: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/rag_api"

    redis_url: str = "redis://localhost:6379/0"
    celery_result_expires_seconds: int = 86400

    object_store_backend: str = "minio"
    object_store_bucket: str = "rag-api-artifacts"
    local_object_store_path: str = "./artifacts"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    default_index_provider: str = "qdrant"
    default_vector_collection_prefix: str = "rag_api"
    chroma_persist_directory: str = "./artifacts/chroma"
    vector_postgres_connection: str | None = None

    feature_enable_llm: bool = False
    feature_enable_graph: bool = False
    feature_enable_raptor: bool = False
    feature_enable_miner_u: bool = False

    graph_backend_default: str = "neo4j"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4jpassword"
    neo4j_database: str = "neo4j"

    llm_provider_default: str = "openai"
    llm_model_default: str = "gpt-4o-mini"
    llm_temperature_default: float = 0.0
    openai_api_key: str | None = None
    openai_api_key_personal: str | None = None
    mistral_api_key: str | None = None
    ya_api_key: str | None = None
    ya_folder_id: str | None = None

    rag_lib_producer_version: str = Field(default_factory=_detect_rag_lib_producer_version)

    page_size_default: int = 20
    page_size_max: int = 200

    worker_enabled: bool = True

    loader_policy_mime_class_map: dict[str, str] = Field(default_factory=_default_loader_policy_mime_class_map)
    loader_policy_extension_class_map: dict[str, str] = Field(default_factory=_default_loader_policy_extension_class_map)
    loader_policy_class_rules: dict[str, dict[str, Any]] = Field(default_factory=_default_loader_policy_class_rules)
    loader_policy_loader_defaults: dict[str, dict[str, Any]] = Field(default_factory=_default_loader_policy_loader_defaults)


settings = Settings()
