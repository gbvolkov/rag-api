from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CreateIndexRequest(BaseModel):
    name: str
    provider: str = "qdrant"
    index_type: str = "segment_vectors"
    config: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)


class IndexOut(BaseModel):
    index_id: str
    project_id: str
    name: str
    provider: str
    index_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    status: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class IndexBuildDocStoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["local_file", "redis"]
    redis_url: str | None = None
    redis_namespace: str | None = None
    redis_ttl: int | None = None

    @model_validator(mode="after")
    def validate_backend_payload(self):
        if self.backend == "redis":
            if not isinstance(self.redis_url, str) or not self.redis_url.strip():
                raise ValueError("doc_store.redis_url is required when backend=redis")
            if not isinstance(self.redis_namespace, str) or not self.redis_namespace.strip():
                raise ValueError("doc_store.redis_namespace is required when backend=redis")
            if not isinstance(self.redis_ttl, int) or self.redis_ttl <= 0:
                raise ValueError("doc_store.redis_ttl is required when backend=redis and must be > 0")
        return self


class IndexBuildDocStoreOut(BaseModel):
    backend: Literal["local_file", "redis"]
    artifact_uri: str
    total_items: int
    redis_namespace: str | None = None
    redis_ttl: int | None = None


class CreateIndexBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_set_id: str
    parent_set_id: str | None = None
    id_key: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    doc_store: IndexBuildDocStoreConfig | None = None
    execution_mode: Literal["sync", "async"] = "sync"

    @model_validator(mode="after")
    def validate_dual_storage_contract(self):
        if self.doc_store is not None:
            if not self.parent_set_id:
                raise ValueError("parent_set_id is required when doc_store is configured")
            if not isinstance(self.id_key, str) or not self.id_key.strip():
                raise ValueError("id_key is required when doc_store is configured")
        return self


class IndexBuildOut(BaseModel):
    build_id: str
    index_id: str
    project_id: str
    source_set_id: str
    parent_set_id: str | None = None
    id_key: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    doc_store: IndexBuildDocStoreOut | None = None
    status: str
    producer_type: str
    producer_version: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
