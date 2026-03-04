from typing import Any

from pydantic import BaseModel, Field


class PipelineRequestMeta(BaseModel):
    loader_type: str | None = None
    loader_params: dict[str, Any] = Field(default_factory=dict)
    split_strategy: str
    splitter_params: dict[str, Any] = Field(default_factory=dict)
    create_index: bool = False
    index_id: str | None = None
    index_params: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str = "sync"


class PipelineResponse(BaseModel):
    project_id: str
    document_id: str | None = None
    document_version_id: str | None = None
    document_set_version_id: str | None = None
    segment_set_version_id: str | None = None
    index_build_id: str | None = None
    job_id: str | None = None
    status: str
