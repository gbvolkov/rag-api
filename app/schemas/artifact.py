from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ArtifactOut(BaseModel):
    artifact_kind: str
    artifact_id: str
    project_id: str
    created_at: datetime
    is_deleted: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
