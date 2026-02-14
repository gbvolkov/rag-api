from datetime import datetime
from typing import Any

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


class CreateIndexBuildRequest(BaseModel):
    chunk_set_version_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str = "sync"


class IndexBuildOut(BaseModel):
    build_id: str
    index_id: str
    project_id: str
    chunk_set_version_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    status: str
    producer_type: str
    producer_version: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
