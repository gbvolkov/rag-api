from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "KBMan Service"
    api_v1_str: str = "/api/v1"
    environment: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/kbman"

    redis_url: str = "redis://localhost:6379/0"
    celery_result_expires_seconds: int = 86400

    object_store_backend: str = "minio"
    object_store_bucket: str = "kbman-artifacts"
    local_object_store_path: str = "./artifacts"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    default_index_provider: str = "qdrant"
    default_vector_collection_prefix: str = "kbman"

    rag_lib_producer_version: str = "93fc9354c70202c6e7d6d814200f7483d0cd8265"

    page_size_default: int = 20
    page_size_max: int = 200

    worker_enabled: bool = True


settings = Settings()
