import json
from importlib import metadata

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


settings = Settings()
