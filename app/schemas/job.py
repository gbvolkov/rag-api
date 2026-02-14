from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    job_id: str
    project_id: str | None
    job_type: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
