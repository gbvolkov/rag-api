# rag-api v0.2.2 Contract Assertion Matrix

This matrix tracks strict API/service behaviors aligned with `rag-lib==0.2.2`.

## Segment Loaders

- `loader_type=docx` uses `DocXLoader` and returns text segments from markdown document output.
- `loader_type=json` accepts `schema`, `schema_dialect`, `output_format`, `ensure_ascii`.
- `loader_type=text` accepts no required params and returns one text document.
- `loader_type=regex` loads raw document then applies `RegexHierarchySplitter`.
- Legacy `loader_type=qa` is rejected with `400 unsupported_loader`.
- Legacy JSON param `jq_schema` is rejected by strict schema/service tests.

## URL Loaders

- `POST /api/v1/projects/{project_id}/segments/url`:
  - accepts only `loader_type=web|web_async`;
  - requires `loader_params.url`;
  - persists crawl diagnostics in segment set params.

## Chunk Strategies

- Supported: `recursive|token|sentence|regex|regex_hierarchy|markdown_hierarchy|json|qa|markdown_table|csv_table|html|semantic`.
- Hierarchical strategies preserve parent/path/level metadata.

## Retrieval

- BM25 path uses `create_bm25_retriever`.
- Rerank path uses `top_k`.
- Graph strategy supports `mode=local|global|hybrid|mix` and full graph query config.

## Graph / RAPTOR Persistence

- Graph query invocations persist `graph_query_runs` rows and JSON artifact payloads.
- RAPTOR transforms persist `raptor_runs` rows and manifest artifacts.
- Pipeline sync persists `ingestion_runs` records.

## User Settings

- `users`, `user_settings`, `user_project_settings` are persisted.
- Resolved settings precedence: user-project override > user global.
