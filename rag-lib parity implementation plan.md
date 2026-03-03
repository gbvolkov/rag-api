# rag-api Strict Parity Plan With rag-lib (No Fallbacks / No Workarounds)

## Summary
Bring `rag-api` to strict contract parity with `rag-lib` developer guide (commit `f142b307...`) for HTTP boundary behavior:

1. Implement every `rag-lib` feature that should be available through HTTP JSON contracts.
2. Keep SDK-only and internal-only `rag-lib` surfaces out of HTTP contracts.
3. Remove all API-layer fallbacks/workarounds that diverge from `rag-lib`.
4. Keep optional `doc_store` build contract with strict `dual_storage` enforcement.
5. Add explicit `length_mode` API support (`string_len` and `token_len`) instead of callable exposure.

---

## Table A: Complete rag-lib Feature List vs rag-api Status and Decision

### A.1 Core + Loaders + Web
| ID | rag-lib feature | Boundary level | Current rag-api status | Decision | Concrete action |
|---|---|---|---|---|---|
| A01 | `core.domain.Segment`, `SegmentType` | HTTP+SDK | Partial | Fix | Enforce strict enum mapping end-to-end; remove silent type coercion to fallback values. |
| A02 | `core.indexer.Indexer` | SDK (used by API core) | Missing | Implement | Rewrite index build execution to use `Indexer` as primary indexing path. |
| A03 | `core.index_builder.IndexBuilder` | Internal-only | Compliant | Keep | Do not expose in HTTP or public API client. |
| A04 | `core.store.JsonFileStore`, `LocalPickleStore` | Internal-only | Compliant | Keep | No HTTP exposure. |
| A05 | `loaders.csv_excel.CSVLoader`, `ExcelLoader` | HTTP+SDK | Implemented | Keep | Maintain support as first-class loaders. |
| A06 | `loaders.data_loaders.JsonLoader`, `SchemaDialect`, `TableLoader`, `TextLoader` | HTTP+SDK | Partial | Fix | Keep loaders; make `schema_dialect` strict enum (no loose strings). |
| A07 | `loaders.data_loaders` helper funcs | Internal/SDK-optional | Compliant | Keep internal | No HTTP exposure. |
| A08 | `loaders.docx.DocXLoader` | HTTP+SDK | Implemented | Keep | No change. |
| A09 | `loaders.html.HTMLLoader` | HTTP+SDK | Implemented | Keep | No change. |
| A10 | `loaders.html.render_html_content` | Internal/SDK-optional | Compliant | Keep internal | No HTTP exposure. |
| A11 | `loaders.miner_u.MinerULoader` strict path | HTTP+SDK | Partial | Fix | Remove API-level MinerU->PDF fallback behavior and fallback params. |
| A12 | `loaders.pdf.PDFLoader` | HTTP+SDK | Implemented | Keep | No change. |
| A13 | `loaders.pymupdf.PyMuPDFLoader` | HTTP+SDK | Implemented | Keep | No change. |
| A14 | `loaders.regex.RegexHierarchyLoader` | HTTP+SDK | Implemented | Keep | No change. |
| A15 | `loaders.web.WebLoader` | HTTP+SDK | Implemented | Keep | Keep serializable config-only exposure. |
| A16 | `loaders.web_async.AsyncWebLoader` | HTTP+SDK | Implemented | Keep | Keep serializable config-only exposure. |
| A17 | `web/web_async` callback params (`login_processor`, `custom_link_extractors`, `playwright_link_extractor`) | Internal/SDK-optional | Compliant | Keep internal | Explicitly forbid callback injection in HTTP schema. |
| A18 | `loaders.web_common.WebCleanupConfig`, `WebLink` | HTTP+SDK | Partial | Fix | Keep typed cleanup config and add typed `WebLink` contract in API response diagnostics. |
| A19 | `loaders.web_common` helper funcs | Internal/SDK-optional | Compliant | Keep internal | No HTTP exposure. |
| A20 | `web_playwright_extractors` configs + `get_playwright_profile_defaults` | HTTP+SDK | Partial | Fix | Keep config dataclasses; add HTTP endpoint for profile/defaults metadata only. |
| A21 | `web_playwright_extractors.build_sync_*`, `build_async_*` | SDK-only | Compliant | Keep out of HTTP | No HTTP exposure. |
| A22 | `web_playwright_extractors.compose_*`, `run_*` | Internal/SDK-optional | Compliant | Keep internal | No HTTP exposure. |

### A.2 Chunkers
| ID | rag-lib feature | Boundary level | Current rag-api status | Decision | Concrete action |
|---|---|---|---|---|---|
| A23 | `chunkers.recursive.RecursiveCharacterTextSplitter` | HTTP+SDK | Implemented | Keep | No change. |
| A24 | `chunkers.token.TokenTextSplitter` | HTTP+SDK | Implemented | Keep | No change. |
| A25 | `chunkers.sentence.SentenceSplitter` | HTTP+SDK | Implemented | Keep | No change. |
| A26 | `chunkers.regex.RegexSplitter` | HTTP+SDK | Implemented | Keep | No change. |
| A27 | `chunkers.regex_hierarchy.RegexHierarchySplitter` | HTTP+SDK | Implemented | Keep | No change. |
| A28 | `chunkers.markdown_hierarchy.MarkdownHierarchySplitter` | HTTP+SDK | Implemented | Keep | No change. |
| A29 | `chunkers.json.JsonSplitter` (+ `min_chunk_size`) | HTTP+SDK | Partial | Fix | Add explicit `min_chunk_size` to API chunker/splitter schema and pass-through. |
| A30 | `chunkers.qa.QASplitter` | HTTP+SDK | Implemented | Keep | No change. |
| A31 | `chunkers.markdown_table.MarkdownTableSplitter` full options | HTTP+SDK | Implemented | Keep | Keep full summarization/splitting options. |
| A32 | `chunkers.csv_table.CSVTableSplitter` full options | HTTP+SDK | Implemented | Keep | Keep full summarization/splitting options. |
| A33 | `chunkers.html.HTMLSplitter` full options | HTTP+SDK | Implemented | Keep | Keep full summarization/splitting options. |
| A34 | `chunkers.semantic.SemanticChunker` strict thresholds | HTTP+SDK | Implemented | Keep | Keep parity of threshold and mode params. |
| A35 | `chunkers.*` callable `length_function` hooks | HTTP: No callable exposure | Partial | Implement | Add `length_mode` (`string_len` / `token_len`) in HTTP schema; implement resolver on API side. |
| A36 | `chunkers.table_rows` utilities | Internal/SDK-optional | Compliant | Keep internal | No HTTP exposure. |
| A37 | `chunkers.language` utilities | Internal/SDK-optional | Compliant | Keep internal | No HTTP exposure. |

### A.3 Retrieval + Graph
| ID | rag-lib feature | Boundary level | Current rag-api status | Decision | Concrete action |
|---|---|---|---|---|---|
| A38 | `retrieval.retrievers`: `create_vector_retriever`, `create_bm25_retriever`, `create_graph_retriever` | SDK factory layer used by API core | Partial | Refactor | Use these factories directly in retrieval service; remove custom provider-special branches. |
| A39 | `retrieval.retrievers.RegexRetriever`, `FuzzyRetriever` | HTTP strategy mapping | Implemented | Keep | Keep mapped via strategy enum. |
| A40 | `retrieval.composition` factories (`ensemble`, `dual_storage`, `scored_dual_storage`, `reranking`, `graph_hybrid`) | SDK factory layer used by API core | Partial | Refactor | Remove custom graph/vector merge branches; use composition factories for all supported paths. |
| A41 | `retrieval.scored_retriever.SearchType`, `HydrationMode` | HTTP+SDK | Implemented | Keep | Keep strict enum parity in schemas. |
| A42 | `retrieval.scored_retriever.ScoredMultiVectorRetriever` | SDK impl | Partial | Fix | Ensure all dual-storage providers run through scored retriever path (no custom qdrant branch). |
| A43 | `retrieval.graph_retriever.GraphRetriever`, `GraphQueryConfig`, `KeywordTiers`, strict errors | SDK (called by API core) | Partial | Fix | Keep strict graph path; preserve and map specific errors without flattening to one generic error. |
| A44 | `graph.store.BaseGraphStore` + `NetworkXGraphStore` strict backend behavior | SDK/internal | Partial | Fix | Remove hidden backend substitution; backend selection must be explicit and strict. |
| A45 | `graph.neo4j_store.Neo4jGraphStore` strict behavior | SDK/internal | Missing strictness | Fix | Remove neo4j->networkx auto-downgrade behavior. |
| A46 | `graph.community.CommunityDetector` | SDK/internal | Implemented | Keep | No change. |

### A.4 Processors + RAPTOR + Summarizers + Factories
| ID | rag-lib feature | Boundary level | Current rag-api status | Decision | Concrete action |
|---|---|---|---|---|---|
| A47 | `processors.enricher.SegmentEnricher` | SDK/internal | Implemented | Keep | No change. |
| A48 | `processors.entity_extractor.EntityExtractor` | SDK/internal | Implemented | Keep | No change. |
| A49 | `processors.community_summarizer.CommunitySummarizer` | SDK/internal | Implemented | Keep | No change. |
| A50 | `processors.raptor.RaptorProcessor` advanced options | SDK/internal | Partial | Expand | Expose supported advanced RAPTOR params (`summary_prompt_template`, clustering options) via HTTP config. |
| A51 | `raptor.*` (`ClusteringService`, `ClusterSummarizer`, `TreeBuilder`) | SDK-only | Compliant boundary | Keep internal | No direct HTTP class exposure; expose only declarative params that map to these components. |
| A52 | `summarizers.table` (`TableSummarizer`, `Mock`, `LLM`) | HTTP+SDK | Implemented | Keep | No change. |
| A53 | `summarizers.table_llm.LLMTableSummarizer(prompt_template, soft_max_chars)` | SDK/HTTP options | Missing | Implement | Add optional `prompt_template` and `soft_max_chars` to table summarizer configs. |
| A54 | `vectors.factory.create_vector_store` | SDK factory layer used by API core | Partial | Refactor | Move index/retrieval vector store instantiation to provider-driven factory path. |
| A55 | `embeddings.factory.create_embeddings_model` | SDK/internal | Implemented | Keep | No change. |
| A56 | `llm.factory.create_llm` | SDK/internal; HTTP JSON args only | Partial | Expand safely | Expose only transport-safe args; keep callbacks/objects out of HTTP. |

---

## Table B: Complete List of rag-api Fallbacks/Workarounds Not Allowed

| ID | Current fallback/workaround in rag-api | Why non-compliant | Removal plan | Acceptance check |
|---|---|---|---|---|
| B01 | MinerU API fallback to PDF loader (`fallback_to_pdf_loader`, `fallback_parse_mode`) | API adds behavior not allowed by strict `rag-lib` boundary | Remove fallback params and fallback code path; fail explicitly with capability/dependency/runtime errors | MinerU missing dependency always returns explicit error; no PDF fallback attempt |
| B02 | BM25 heuristic fallback when `create_bm25_retriever` fails | Silent algorithm substitution | Remove fallback scorer; propagate explicit dependency/runtime error | When BM25 dependency missing, retrieval fails with explicit error |
| B03 | Ensemble silently ignores BM25 source errors (`except: continue`) | Silent degradation | Convert to strict validation: invalid source/dependency => error | Bad ensemble source returns `400 invalid_ensemble_sources` with details |
| B04 | Ensemble qdrant vector source converted to BM25 over vector hits | Custom workaround, not `rag-lib` composition contract | Use proper vector retriever in ensemble source for all providers | qdrant vector source participates as vector retriever, not BM25 proxy |
| B05 | Rerank with `base.type=vector` returns vector docs directly (no rerank) | Behavior diverges from reranking contract | Always wrap base retriever with `create_reranking_retriever` | Rerank with vector base changes ordering by reranker logic |
| B06 | Dual-storage custom qdrant branch with manual hydration | Custom implementation bypassing `ScoredMultiVectorRetriever` | Remove qdrant special branch; use `create_scored_dual_storage_retriever` uniformly | Dual-storage path identical across providers |
| B07 | Vector qdrant manual `query_points` path + hardcoded `mmr` rejection | Provider-specific workaround and divergence from retriever factory behavior | Use `create_vector_retriever` on materialized vector store for qdrant too | `mmr` behavior follows rag-lib/vector store support (success or explicit backend error) |
| B08 | Custom `_merge_scored_lists` for `graph_hybrid` | Reinvented composition path | Use `create_graph_hybrid_retriever` | Graph hybrid result composition comes from rag-lib composition |
| B09 | Neo4j auto-downgrade to networkx in dev/local/test | Hidden fallback forbidden by guide | Remove auto-downgrade; require explicit backend/dependency | Missing neo4j dependency gives explicit missing dependency error |
| B10 | Graph query uses ephemeral FAISS + MockEmbeddings regardless configured index | API-only workaround, breaks strict graph/vector parity | Build/use vector store consistent with build/provider config | Graph retrieval uses configured vector backend/config path |
| B11 | Graph exceptions flattened to generic `graph_query_failed` | Loses strict error contract from rag-lib | Map `GraphConfigurationError`, `GraphCapabilityError`, `GraphDataError` to explicit API error codes | Each error class maps to distinct API code/status |
| B12 | Segment type coercion fallbacks (`unknown -> other` / `unknown -> TEXT`) | Silent data mutation | Validate and fail on invalid persisted type or normalize at write-time only with strict enum set | Invalid type cannot silently pass through retrieval/serialization |
| B13 | Local Celery stub fallback class when Celery import fails | Runtime fallback outside strict contract posture | Remove stub; require Celery dependency for async mode or disable async explicitly by feature flag | Async endpoints fail clearly when Celery unavailable |
| B14 | README contract still documents fallback params and legacy loader fields (`qa`, `jq_schema`) | Documentation-level workaround/legacy drift | Rewrite API docs to strict current contract | README and OpenAPI agree on strict fields only |

---

## Public API / Interface Changes (Decision-Complete)

1. Splitter/chunker length mode (HTTP JSON-safe only):
- Add to both segment split params and chunker params:
  - `length_mode: "string_len" | "token_len"` (default `"string_len"`).
  - `length_mode_config` optional with `encoding_name` and `model_name`.
- `token_len` implementation on API side via tokenizer-backed length function.
- No callable exposure in HTTP.

2. Strict dialect and strategy enums:
- Make `schema_dialect` strict enum values matching `rag_lib.loaders.data_loaders.SchemaDialect`.
- Keep retrieval `SearchType` and `HydrationMode` strict string enums.

3. Remove fallback-only API fields:
- Remove `fallback_to_pdf_loader`, `fallback_parse_mode` from MinerU HTTP payload contract.
- Reject unknown legacy fields with explicit validation error.

4. Playwright HTTP surface:
- Keep only config dataclasses and profile/default metadata in HTTP contracts.
- Do not expose builder/composer/runner callable surfaces.

5. Table summarizer parity:
- Extend summarizer config with `prompt_template` and `soft_max_chars` options for LLM summarizer.

6. Index build / doc_store contract:
- Keep `doc_store` optional at build.
- Keep strict dual-storage runtime requirement:
  - missing doc_store -> `doc_store_required_for_dual_storage`
  - id_key mismatch -> `dual_storage_id_key_mismatch`

---

## Implementation Plan (Ordered)

1. Contract hardening pass:
- Update schemas for strict enums and new `length_mode`.
- Remove legacy/fallback params from loader and docs.
- Add strict validation tests first.

2. Retrieval core rewrite to rag-lib factories/composition:
- Remove manual qdrant vector and dual-storage branches.
- Remove BM25 fallback and ensemble silent continuations.
- Ensure rerank always applies reranker.
- Replace custom graph_hybrid merge with composition factory.

3. Graph strictness rewrite:
- Remove backend auto-downgrade logic.
- Replace generic graph error flattening with typed error mapping.
- Replace ephemeral FAISS+mock vector workaround with configured vector path.

4. Index build alignment:
- Use `Indexer`/factory-driven vector creation path.
- Preserve optional `doc_store` artifact behavior and strict dual-storage contract.
- Keep build success without `doc_store`.

5. Chunk/segment split parity:
- Implement `length_mode` resolver and wire to all applicable splitters.
- Add explicit `min_chunk_size` support for JSON splitter in API schema/pass-through.

6. Summarizer parity:
- Add `prompt_template` and `soft_max_chars` to table summarization configs in API.

7. Docs/examples/client alignment:
- Update README/OpenAPI examples to strict contract.
- Keep `examples/01_text_basic.py` dual-storage flow with explicit `doc_store`.
- Keep `examples/api_client.py` optional `doc_store` payload behavior.

8. Regression and compatibility tests:
- Add/update tests below and run full integration matrix.

---

## Test Cases and Scenarios

1. Existing required doc_store scenarios (must pass):
- Build without `doc_store` -> success.
- Build without `doc_store` + `dual_storage` retrieval -> explicit error.
- Build with `doc_store` + non-dual retrieval -> success.
- Build with `doc_store` + dual retrieval -> success.
- Build with `doc_store` + id_key mismatch -> explicit error.
- Provider regression (`qdrant/faiss/chroma/postgres`) for non-dual retrieval remains green.

2. New strict no-fallback tests:
- MinerU missing dependency never triggers PDF fallback.
- BM25 dependency failure returns explicit error (no heuristic fallback).
- Ensemble invalid source/dependency errors are explicit.
- Rerank with vector base actually reranks.
- Dual-storage path uses same retriever composition for qdrant and non-qdrant.
- Graph backend `neo4j` missing dependency errors explicitly (no auto networkx switch).
- Graph error mapping preserves typed error codes.
- No silent segment-type coercion in runtime serialization.

3. Length mode tests:
- `length_mode=string_len` default behavior unchanged.
- `length_mode=token_len` changes split boundaries deterministically.
- Missing tokenizer dependency for token mode returns explicit dependency error.

4. 01_text_basic acceptance:
- Segment step produces multiple logical segments.
- Chunking step can be repeated.
- Index build with explicit doc_store succeeds.
- Dual-storage retrieval succeeds with parent hydration.

---

## Assumptions and Defaults

1. `rag-api` remains an HTTP JSON boundary only; SDK-only `rag_lib` surfaces are not directly exposed in HTTP.
2. If behavior is unsupported or failing in `rag_lib`, `rag-api` returns explicit errors; it does not patch, fallback, or emulate.
3. `doc_store` is opt-in at build time and mandatory only for `dual_storage` retrieval.
4. Default `length_mode` is `string_len`; token mode is opt-in.
5. Backward compatibility for legacy fallback fields is not preserved; migration is explicit and strict.
