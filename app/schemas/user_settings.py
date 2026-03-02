from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UpsertUserRequest(BaseModel):
    external_subject: str
    profile: dict[str, Any] = Field(default_factory=dict)


class UserOut(BaseModel):
    user_id: str
    external_subject: str
    profile: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class UserSettingsRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class UserSettingsOut(BaseModel):
    user_id: str
    settings: dict[str, Any] = Field(default_factory=dict)
    resolved_settings: dict[str, Any] = Field(default_factory=dict)

