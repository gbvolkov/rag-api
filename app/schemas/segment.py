from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SegmentType(str, Enum):
    text = "text"
    table = "table"
    image = "image"
    audio = "audio"
    code = "code"
    other = "other"


class SegmentItemOut(BaseModel):
    item_id: str
    position: int
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_id: str | None = None
    level: int = 0
    path: list[str] = Field(default_factory=list)
    type: SegmentType = SegmentType.text
    original_format: str = "text"


class SegmentSetOut(BaseModel):
    segment_set_version_id: str
    project_id: str
    document_version_id: str | None = None
    parent_segment_set_version_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    producer_type: str
    producer_version: str
    is_active: bool
    is_deleted: bool
    created_at: datetime
    total_items: int = 0


class CreateSegmentsFromDocumentSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    split_strategy: str = Field(
        description=(
            "Required split strategy. Supported: "
            "recursive|token|sentence|regex|regex_hierarchy|markdown_hierarchy|"
            "json|qa|markdown_table|csv_table|html|semantic|identity."
        ),
        examples=["regex", "markdown_hierarchy", "identity"],
    )
    splitter_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Split-strategy-specific options. For strategy=regex, 'pattern' is required.",
        examples=[{"pattern": "(?=##Term:)"}],
    )
    params: dict[str, Any] = Field(default_factory=dict)


class ClonePatchSegmentRequest(BaseModel):
    item_id: str
    patch: dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)


class SplitSegmentsRequest(BaseModel):
    strategy: str = Field(
        description=(
            "Split strategy. Supported: recursive|token|sentence|regex|regex_hierarchy|markdown_hierarchy|"
            "json|qa|markdown_table|csv_table|html|semantic."
        ),
        examples=["regex", "recursive"],
    )
    splitter_params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Strategy-specific options. For strategy=regex, 'pattern' is required and passed to Python re.split. "
            "If the pattern uses capturing groups, those captures are returned as standalone segments."
        ),
        examples=[
            {"pattern": "\\.\\s+"},
            {"pattern": "(?=Section\\s+\\d+:)"},
            {"pattern": "(\\.\\s+)"},
        ],
    )
    params: dict[str, Any] = Field(default_factory=dict)


class SegmentSetWithItems(BaseModel):
    segment_set: SegmentSetOut
    items: list[SegmentItemOut]


class EnrichSegmentsRequest(BaseModel):
    execution_mode: str = "sync"
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RaptorSegmentsRequest(BaseModel):
    execution_mode: str = "async"
    max_levels: int = 3
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    embedding_provider: str = "openai"
    embedding_model_name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RaptorRunOut(BaseModel):
    raptor_run_id: str
    project_id: str
    source_segment_set_version_id: str
    output_segment_set_version_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    status: str
    created_at: datetime
