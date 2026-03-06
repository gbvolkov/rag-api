from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentItemOut(BaseModel):
    item_id: str
    position: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    original_format: str = "text"


class DocumentSetOut(BaseModel):
    document_set_version_id: str
    project_id: str
    document_version_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    producer_type: str
    producer_version: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
    total_items: int = 0


class DocumentSetWithItems(BaseModel):
    document_set: DocumentSetOut
    items: list[DocumentItemOut]


class LoadDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loader_type: str | None = Field(
        default=None,
        description="Optional loader override. When omitted, loader is resolved from MIME/extension policy.",
    )
    loader_params: dict[str, Any] = Field(default_factory=dict)


class LoadDocumentsFromUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loader_type: str | None = Field(
        default=None,
        description="Optional URL-loader override. Allowed: web|web_async by policy.",
    )
    loader_params: dict[str, Any] = Field(default_factory=dict)


class LoadDocumentsFromUrlSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loader_type: str | None = Field(
        default=None,
        description="Optional URL-loader override. Allowed: web|web_async by policy.",
    )
    loader_params: dict[str, Any] = Field(default_factory=dict)


class LoadDocumentsFromUrlSubmitResponse(BaseModel):
    mode: Literal["async"] = "async"
    job_id: str
    status: Literal["queued"] = "queued"
