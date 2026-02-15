from typing import Literal

from pydantic import BaseModel, Field


class TableSummarizerConfig(BaseModel):
    type: Literal["mock", "llm"] = "mock"
    llm_provider: str | None = None
    model: str | None = None
    temperature: float | None = None


class TableSummarizeRequest(BaseModel):
    markdown_table: str = Field(min_length=1)
    summarizer: TableSummarizerConfig = Field(default_factory=TableSummarizerConfig)


class TableSummarizeResponse(BaseModel):
    summary: str
    summarizer_type: str

