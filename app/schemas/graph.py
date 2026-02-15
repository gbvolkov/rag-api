from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateGraphBuildRequest(BaseModel):
    source_type: Literal["segment_set", "chunk_set"] = "segment_set"
    source_id: str
    backend: Literal["neo4j", "networkx"] | None = None
    extract_entities: bool = True
    detect_communities: bool = False
    summarize_communities: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    search_depth: int = 1
    params: dict[str, Any] = Field(default_factory=dict)
    execution_mode: Literal["sync", "async"] = "async"


class GraphBuildOut(BaseModel):
    graph_build_id: str
    project_id: str
    source_type: str
    source_id: str
    backend: str
    params: dict[str, Any] = Field(default_factory=dict)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    status: str
    producer_type: str
    producer_version: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

