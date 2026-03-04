# rag-api v0.2.2 Contract Assertion Matrix

This matrix tracks strict API/service behaviors aligned with `rag-lib==0.2.2`.

## Load Stage

- `POST /api/v1/document_versions/{version_id}/load_documents` loads and persists `Document[]`.
- `POST /api/v1/projects/{project_id}/load_documents/url` loads URL content and persists `Document[]`.
- Supported loaders: `pdf|miner_u|pymupdf|docx|html|csv|excel|json|text|table|regex|web|web_async`.
- `loader_type=qa` is rejected with `400 unsupported_loader`.
- URL sources accept only `web|web_async`.

## Segment Stage

- `POST /api/v1/document_sets/{document_set_version_id}/segments` creates `Segment[]` from loaded documents.
- Request is split-only: `split_strategy`, `splitter_params`, `params`.
- Loader fields are not accepted in segment-stage requests.
- Legacy combined ingestion endpoints are removed:
  - `POST /api/v1/document_versions/{version_id}/segments`
  - `POST /api/v1/projects/{project_id}/segments/url`

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
