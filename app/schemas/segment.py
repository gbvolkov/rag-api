from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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


class CreateSegmentsRequest(BaseModel):
    loader_type: str = Field(
        description=(
            "Segment loader type. Supported: pdf|miner_u|docx|csv|excel|json|qa|table|regex. "
            "Regex and DOCX regex_patterns details are documented in README sections "
            "'Regex Loader Contract' and 'DOCX + regex_patterns hierarchy behavior'."
        ),
        examples=["regex", "docx", "pdf"],
    )
    loader_params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Loader-specific options. "
            "Regex loader expects patterns/exclude_patterns/include_parent_content. "
            "DOCX loader may use regex_patterns for additional hierarchy splitting."
        ),
        examples=[
            {
                "patterns": [
                    [1, "^Section\\s+(\\d+):"],
                    [2, "^Subsection\\s+(\\d+\\.\\d+):"],
                ],
                "exclude_patterns": ["^\\s*#"],
                "include_parent_content": 2,
            },
            {
                "patterns": [
                    {"level": 1, "pattern": "^Chapter\\s+(.+)$"},
                    {"level": 2, "pattern": ["^Section\\s+(.+)$", "^Clause\\s+(.+)$"]},
                ]
            },
            {
                "regex_patterns": [[2, "^Subsection\\s+(\\d+\\.\\d+):"]],
                "exclude_patterns": ["^DRAFT\\b"],
                "include_parent_content": True,
            },
        ],
    )
    source_text: str | None = Field(
        default=None,
        description=(
            "Optional direct text input. When provided, loader_type/loader_params are bypassed and "
            "a single text segment is emitted."
        ),
        examples=["Inline text to segment without reading the uploaded file."],
    )


class ClonePatchSegmentRequest(BaseModel):
    item_id: str
    patch: dict[str, Any]
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
