from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChunkItemOut(BaseModel):
    item_id: str
    position: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_id: str | None = None
    level: int = 0
    path: list[str] = Field(default_factory=list)
    type: str = "text"
    original_format: str = "text"


class ChunkSetOut(BaseModel):
    chunk_set_version_id: str
    project_id: str
    segment_set_version_id: str
    parent_chunk_set_version_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    producer_type: str
    producer_version: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
    total_items: int = 0


class ChunkFromSegmentRequest(BaseModel):
    strategy: str = "recursive"
    chunker_params: dict[str, Any] = Field(default_factory=dict)


class ClonePatchChunkRequest(BaseModel):
    item_id: str
    patch: dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)


class ChunkSetWithItems(BaseModel):
    chunk_set: ChunkSetOut
    items: list[ChunkItemOut]
