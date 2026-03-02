from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateIndexRequest(BaseModel):
    name: str
    provider: str = "qdrant"
    index_type: str = "chunk_vectors"
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
    source: Literal["auto", "segment_set", "parent_chunk_set"] = "auto"
    id_key: str = "parent_id"


class IndexBuildDocStoreOut(BaseModel):
    source: Literal["segment_set", "parent_chunk_set"]
    source_id: str
    id_key: str
    artifact_uri: str
    total_items: int


class CreateIndexBuildRequest(BaseModel):
    chunk_set_version_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    doc_store: IndexBuildDocStoreConfig | None = None
    execution_mode: str = "sync"


class IndexBuildOut(BaseModel):
    build_id: str
    index_id: str
    project_id: str
    chunk_set_version_id: str
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
