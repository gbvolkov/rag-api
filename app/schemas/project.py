from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectSettings(BaseModel):
    default_retrieval_preset: str | None = None
    default_chunking_preset: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    settings: ProjectSettings = Field(default_factory=ProjectSettings)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    settings: ProjectSettings | None = None


class ProjectOut(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    settings: ProjectSettings
    created_at: datetime
    updated_at: datetime
