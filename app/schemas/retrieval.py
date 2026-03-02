from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class VectorConfig(BaseModel):
    type: Literal["vector"] = "vector"
    k: int = 10
    search_type: str = "similarity"
    score_threshold: float | None = None
    filter: dict[str, Any] | None = None


class BM25Config(BaseModel):
    type: Literal["bm25"] = "bm25"
    k: int = 10


class RegexConfig(BaseModel):
    type: Literal["regex"] = "regex"
    pattern: str


class FuzzyConfig(BaseModel):
    type: Literal["fuzzy"] = "fuzzy"
    threshold: int = 80
    mode: Literal["partial_ratio", "ratio", "token_set_ratio", "wratio"] = "partial_ratio"


class EnsembleConfig(BaseModel):
    type: Literal["ensemble"] = "ensemble"
    sources: list[dict[str, Any]] = Field(default_factory=list)
    weights: list[float] | None = None


class RerankConfig(BaseModel):
    type: Literal["rerank"] = "rerank"
    base: dict[str, Any]
    model_name: str = "BAAI/bge-reranker-base"
    top_k: int = 5
    max_score_ratio: float = 0.0
    device: str = "cpu"


class DualStorageConfig(BaseModel):
    type: Literal["dual_storage"] = "dual_storage"
    vector_search: dict[str, Any] = Field(default_factory=lambda: {"k": 10})
    id_key: str = "parent_id"
    search_type: Literal["similarity", "similarity_score_threshold", "mmr"] = "similarity"
    score_threshold: float | None = None
    hydration_mode: Literal["parents_replace", "children_enriched", "children_plus_parents"] = "parents_replace"
    search_kwargs: dict[str, Any] = Field(default_factory=dict)
    enrichment_separator: str = "\n\n--- MATCHED CHILD CHUNK ---\n\n"


class GraphConfig(BaseModel):
    type: Literal["graph"] = "graph"
    graph_build_id: str
    mode: Literal["local", "global", "hybrid", "mix"] = "hybrid"
    top_k_entities: int = 12
    top_k_relations: int = 24
    top_k_chunks: int = 10
    max_hops: int = 2
    min_score: float = 0.15
    use_rerank: bool = True
    enable_keyword_extraction: bool = False
    vector_relevance_mode: Literal["strict_0_1", "normalize_minmax"] = "strict_0_1"
    token_budget_total: int = 3500
    token_budget_entities: int = 700
    token_budget_relations: int = 900
    token_budget_chunks: int = 1900


class GraphHybridConfig(BaseModel):
    type: Literal["graph_hybrid"] = "graph_hybrid"
    graph_build_id: str
    mode: Literal["local", "global", "hybrid", "mix"] = "hybrid"
    top_k_entities: int = 12
    top_k_relations: int = 24
    top_k_chunks: int = 10
    max_hops: int = 2
    min_score: float = 0.15
    use_rerank: bool = True
    enable_keyword_extraction: bool = False
    vector_relevance_mode: Literal["strict_0_1", "normalize_minmax"] = "strict_0_1"
    token_budget_total: int = 3500
    token_budget_entities: int = 700
    token_budget_relations: int = 900
    token_budget_chunks: int = 1900
    vector: dict[str, Any] = Field(default_factory=lambda: {"k": 10, "search_type": "similarity", "score_threshold": None})
    weights: list[float] | None = None


StrategyConfig = VectorConfig | BM25Config | RegexConfig | FuzzyConfig | EnsembleConfig | RerankConfig | DualStorageConfig | GraphConfig | GraphHybridConfig


class RetrieveRequest(BaseModel):
    query: str
    target: str = Field(default="chunk_set", description="chunk_set|segment_set|index_build|graph_build")
    target_id: str | None = None
    strategy: StrategyConfig = Field(discriminator="type")
    persist: bool = True
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
