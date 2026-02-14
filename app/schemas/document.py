from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DocumentOut(BaseModel):
    document_id: str
    project_id: str
    filename: str
    mime: str
    storage_uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime


class DocumentVersionOut(BaseModel):
    version_id: str
    document_id: str
    content_hash: str
    parser_params: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    producer_type: str
    producer_version: str
    status: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
