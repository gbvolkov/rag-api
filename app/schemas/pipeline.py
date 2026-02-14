from typing import Any

from pydantic import BaseModel, Field


class PipelineRequestMeta(BaseModel):
    loader_type: str
    loader_params: dict[str, Any] = Field(default_factory=dict)
    chunk_strategy: str = "recursive"
    chunker_params: dict[str, Any] = Field(default_factory=dict)
    create_index: bool = False
    index_id: str | None = None
    index_params: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str = "sync"


class PipelineResponse(BaseModel):
    project_id: str
    document_id: str
    document_version_id: str
    segment_set_version_id: str
    chunk_set_version_id: str
    index_build_id: str | None = None
    job_id: str | None = None
    status: str
