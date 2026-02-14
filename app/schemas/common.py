from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class ErrorPayload(BaseModel):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    hint: str | None = None


class SoftDeleteRequest(BaseModel):
    reason: str | None = None


class RestoreResponse(BaseModel):
    ok: bool
    artifact_kind: str
    artifact_id: str
    restored_at: datetime


class DeleteResponse(BaseModel):
    ok: bool
    artifact_kind: str
    artifact_id: str
    deleted_at: datetime
