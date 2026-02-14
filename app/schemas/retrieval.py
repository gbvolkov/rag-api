from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class VectorConfig(BaseModel):
    type: Literal["vector"] = "vector"
    k: int = 10
    search_type: str = "similarity"
    score_threshold: float | None = None


class BM25Config(BaseModel):
    type: Literal["bm25"] = "bm25"
    k: int = 10


class RegexConfig(BaseModel):
    type: Literal["regex"] = "regex"
    pattern: str


class FuzzyConfig(BaseModel):
    type: Literal["fuzzy"] = "fuzzy"
    threshold: int = 80


class EnsembleConfig(BaseModel):
    type: Literal["ensemble"] = "ensemble"
    sources: list[dict[str, Any]] = Field(default_factory=list)
    weights: list[float] | None = None


class RerankConfig(BaseModel):
    type: Literal["rerank"] = "rerank"
    base: dict[str, Any]
    model_name: str = "BAAI/bge-reranker-base"
    top_n: int = 5
    device: str = "cpu"


class DualStorageConfig(BaseModel):
    type: Literal["dual_storage"] = "dual_storage"
    vector_search: dict[str, Any] = Field(default_factory=dict)
    id_key: str = "segment_id"


StrategyConfig = VectorConfig | BM25Config | RegexConfig | FuzzyConfig | EnsembleConfig | RerankConfig | DualStorageConfig


class RetrieveRequest(BaseModel):
    query: str
    target: str = Field(default="chunk_set", description="chunk_set|segment_set|index_build")
    target_id: str | None = None
    strategy: StrategyConfig = Field(discriminator="type")
    persist: bool = False
    limit: int = 20
    cursor: str | None = None


class RetrievedDocument(BaseModel):
    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None


class RetrieveResponse(BaseModel):
    items: list[RetrievedDocument]
    next_cursor: str | None = None
    has_more: bool = False
    strategy: str
    target: str
    target_id: str | None = None
    total: int
    run_id: str | None = None


class RetrievalRunOut(BaseModel):
    run_id: str
    project_id: str
    strategy: str
    query: str
    target_type: str
    target_id: str | None
    params: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str | None = None
    is_deleted: bool
    created_at: datetime
