from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SegmentType(str, Enum):
    text = "text"
    table = "table"
    image = "image"
    audio = "audio"
    code = "code"
    other = "other"


class SegmentItemOut(BaseModel):
    item_id: str
    position: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_id: str | None = None
    level: int = 0
    path: list[str] = Field(default_factory=list)
    type: SegmentType = SegmentType.text
    original_format: str = "text"


class SegmentSetOut(BaseModel):
    segment_set_version_id: str
    project_id: str
    document_version_id: str | None = None
    parent_segment_set_version_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    producer_type: str
    producer_version: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
    total_items: int = 0


class CreateSegmentsRequest(BaseModel):
    loader_type: str = Field(description="pdf|docx|csv|excel|json|qa|table")
    loader_params: dict[str, Any] = Field(default_factory=dict)
    source_text: str | None = None


class ClonePatchSegmentRequest(BaseModel):
    item_id: str
    patch: dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)


class SegmentSetWithItems(BaseModel):
    segment_set: SegmentSetOut
    items: list[SegmentItemOut]
