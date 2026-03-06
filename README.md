# RAG API

Project-scoped document ingestion, segmentation, chunking, indexing, retrieval, and artifact lifecycle service built on top of `rag_lib`.

## Breaking Change: Load Then Split

Ingestion now follows strict `rag_lib` semantics:

1. Load documents with a loader (`Document[]` output).
2. Create segments from a loaded document set with an independent split strategy (`Segment[]` output).

Canonical endpoints:

- Load from uploaded file:
  - `POST /api/v1/document_versions/{version_id}/load_documents`
- Load from URL:
  - `POST /api/v1/projects/{project_id}/load_documents/url`
- Inspect loaded document sets:
  - `GET /api/v1/projects/{project_id}/document_sets`
  - `GET /api/v1/document_sets/{document_set_version_id}`
- Create segments from loaded documents:
  - `POST /api/v1/document_sets/{document_set_version_id}/segments`
- Re-split an existing segment set:
  - `POST /api/v1/segment_sets/{segment_set_id}/split`

Removed (strict cutover):

- `POST /api/v1/document_versions/{version_id}/segments`
- `POST /api/v1/projects/{project_id}/segments/url`

Detailed contract and policy mapping:
- [docs/rag_lib_load_split_contract.md](docs/rag_lib_load_split_contract.md)

## Stack

- API: FastAPI (`/api/v1`)
- DB: PostgreSQL (metadata and lineage)
- Object store: MinIO (raw files and generated artifacts)
- Vector store: Qdrant / FAISS / Chroma / Postgres(PGVector) (depending on index provider)
- Async runtime: Celery + Redis

## Run

### Standard Docker compose

```bash
docker compose up --build
```

For subsequent starts (when dependencies/config did not change), skip rebuild:

```bash
docker compose up
```

- API: `http://localhost:8000`
- OpenAPI JSON: `http://localhost:8000/api/v1/openapi.json`

### If host ports are already occupied

Use an override that clears dependency host-port mappings:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-noports.yml up -d --build
```

Subsequent starts:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-noports.yml up -d
```

This keeps API on `:8000` while avoiding local collisions for Postgres/Redis/MinIO/Qdrant.

## API Conventions

### Base URLs

- Service root: `/`
- Health: `/health`
- Versioned API root: `/api/v1`

### Auth

No authentication/authorization middleware is currently enforced.

### Content types

- Most endpoints: `application/json`
- Upload endpoints:
  - `POST /api/v1/projects/{project_id}/documents`
  - `POST /api/v1/projects/{project_id}/pipeline/file`
  - use `multipart/form-data`

### Error payload format

Application-level errors are raised as:

```json
{
  "detail": {
    "code": "machine_code",
    "message": "Human readable message",
    "detail": {},
    "hint": null
  }
}
```

FastAPI/Pydantic validation errors (for malformed inputs) use standard `422` schema.

### Cursor pagination

Two APIs use offset-based cursor pagination with Base64-encoded offsets:

- `GET /api/v1/projects/{project_id}/artifacts`
- `POST /api/v1/projects/{project_id}/retrieve`

Response fields:

- `next_cursor`: opaque cursor for next page, or `null`
- `has_more`: boolean
- `total`: total matching records before slicing

If an invalid cursor is supplied, it is treated as offset `0`.

## Endpoint Reference

This section defines request parameters for every method. It is intentionally explicit for frontend implementation.

Conventions used below:

- `Required` means required by request schema/signature.
- `Default` means applied when field is omitted.
- `Allowed` lists accepted enum-like values.
- For `object` fields, this section describes currently implemented keys and behavior.
- Fields described as "free-form" accept arbitrary JSON and are persisted; no strict key validation is enforced by API.

### GET `/`

| Parameter location | Parameters |
|---|---|
| path | none |
| query | none |
| body | none |

Response `200`:

| Field | Type | Notes |
|---|---|---|
| `service` | string | service name (`settings.app_name`) |
| `api` | string | API prefix (`settings.api_v1_str`, usually `/api/v1`) |

### GET `/health`

| Parameter location | Parameters |
|---|---|
| path | none |
| query | none |
| body | none |

Response `200`:

| Field | Type | Notes |
|---|---|---|
| `status` | string | constant `"ok"` |

### POST `/api/v1/projects`

Path/query params: none.

Request body (`CreateProjectRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `name` | string | yes | - | `1..200` chars |
| `description` | string \| null | no | `null` | max `2000` chars |
| `settings` | object | no | `{}` | project defaults, see nested fields |

`settings` nested fields:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `default_retrieval_preset` | string \| null | no | `null` | optional label |
| `default_chunking_preset` | string \| null | no | `null` | optional label |
| `extra` | object | no | `{}` | arbitrary JSON for frontend/project metadata |

Response `200`: `ProjectOut`

Behavior notes:

- Creates a new non-deleted project row.
- `settings` is stored as JSON and returned as structured object.

### GET `/api/v1/projects`

| Parameter location | Parameters |
|---|---|
| path | none |
| query | none |
| body | none |

Response `200`: `ProjectOut[]`

Behavior notes:

- Returns only non-deleted projects.
- Sorted by `created_at desc` (newest first).

### GET `/api/v1/projects/{project_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`: `ProjectOut`

Behavior notes:

- Returns `404 project_not_found` if project is missing or soft-deleted.

### PATCH `/api/v1/projects/{project_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Request body (`UpdateProjectRequest`, all optional):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `name` | string \| null | no | `null` | if provided, `1..200` chars |
| `description` | string \| null | no | `null` | if provided, max `2000` chars |
| `settings` | object \| null | no | `null` | full replacement of project settings |

`settings` nested fields are identical to `POST /projects`.

Response `200`: `ProjectOut`

Behavior notes:

- Partial update: omitted fields stay unchanged.
- `settings` replaces the full project settings object when provided.

### DELETE `/api/v1/projects/{project_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`:

| Field | Type |
|---|---|
| `ok` | boolean |
| `project_id` | string |

Behavior notes:

- Soft delete only (`is_deleted=true`), no physical row removal.
- Deleted project disappears from project list and project-scoped routes return `404`.

### POST `/api/v1/projects/{project_id}/documents`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Multipart form fields:

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `file` | binary file | yes | - | uploaded bytes |
| `parser_params_json` | string \| null | no | `null` | must be valid JSON string; parsed via `json.loads` |

`parser_params_json` behavior:

- Parsed JSON is persisted as `document_version.parser_params`.
- No strict key validation is applied.
- Typical frontend keys: `loader_type`, `loader_params`, or any ingestion metadata tags.

Response `200`:

| Field | Type | Notes |
|---|---|---|
| `document` | `DocumentOut` | created document record |
| `document_version` | `DocumentVersionOut` | active version created for uploaded file |

Behavior notes:

- Upload MIME is normalized before persistence.
- Raw bytes are stored in object storage and linked by `storage_uri`/`artifact_uri`.

### GET `/api/v1/projects/{project_id}/documents`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`: `DocumentOut[]`

Behavior notes:

- Returns only non-deleted documents for project.
- Sorted by `created_at desc`.

### GET `/api/v1/documents/{document_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `document_id` | string | yes |

Query/body params: none.

Response `200`: `DocumentOut`

Behavior notes:

- Returns `404 document_not_found` when missing or soft-deleted.

### GET `/api/v1/documents/{document_id}/versions`

Path params:

| Name | Type | Required |
|---|---|---|
| `document_id` | string | yes |

Query/body params: none.

Response `200`: `DocumentVersionOut[]`

Behavior notes:

- Returns only non-deleted versions for the document.
- Sorted by `created_at desc`.

### GET `/api/v1/document_versions/{version_id}/content`

Path params:

| Name | Type | Required |
|---|---|---|
| `version_id` | string | yes |

Query/body params: none.

Response `200`:

- Body: raw bytes (`application/*`, `text/*`, etc., based on effective preview MIME)
- Headers:
  - `Content-Type`: effective preview MIME
  - `Content-Disposition`: `inline; filename*=UTF-8''<filename>`
  - `ETag`: version `content_hash`
  - `X-Content-Type-Options: nosniff`

Behavior notes:

- Effective preview MIME may be inferred from filename when stored MIME is generic.
- Returns `404 document_version_not_found` or `404 document_content_not_found` when unresolved.

### POST `/api/v1/document_versions/{version_id}/load_documents`

Path params:

| Name | Type | Required |
|---|---|---|
| `version_id` | string | yes |

Request body (`LoadDocumentsRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `loader_type` | string \| null | no | `null` | loader override; if omitted, loader is resolved by MIME/extension policy |
| `loader_params` | object | no | `{}` | merged on top of loader default params |

Response `200`: `DocumentSetWithItems`

Behavior notes:

- Persists one `document_set_version` and all returned `document_items`.
- File-based load deactivates prior active document sets for the same `document_version_id`.
- Loader policy controls defaults and allowed overrides.

### POST `/api/v1/projects/{project_id}/load_documents/url`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Request body (`LoadDocumentsFromUrlRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `loader_type` | string \| null | no | `null` | allowed: `web` or `web_async` |
| `loader_params` | object | yes | `{}` | must include `url` |

Response `200`: `DocumentSetWithItems`

### GET `/api/v1/projects/{project_id}/document_sets`

Response `200`: `DocumentSetOut[]`

### GET `/api/v1/document_sets/{document_set_version_id}`

Response `200`: `DocumentSetWithItems`

### POST `/api/v1/document_sets/{document_set_version_id}/segments`

Path params:

| Name | Type | Required |
|---|---|---|
| `document_set_version_id` | string | yes |

Request body (`CreateSegmentsFromDocumentSetRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `split_strategy` | string | yes | - | splitter/chunker strategy |
| `splitter_params` | object | no | `{}` | strategy-specific settings |
| `params` | object | no | `{}` | free-form metadata params |

Response `200`: `SegmentSetWithItems`

Behavior notes:

- Segment creation is split-only at this stage; loader fields are not part of this request.
- For file-backed lineage, active-segment semantics remain tied to `document_version_id`.

### GET `/api/v1/projects/{project_id}/segment_sets`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`: `SegmentSetOut[]`

Behavior notes:

- Returns only non-deleted segment sets for the project.
- Sorted by `created_at desc`.
- `total_items` is computed per segment set.

### GET `/api/v1/segment_sets/{segment_set_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `segment_set_id` | string | yes |

Query/body params: none.

Response `200`: `SegmentSetWithItems`

Behavior notes:

- Returns segment set plus all segment items ordered by `position asc`.
- Returns `404 segment_set_not_found` when missing or soft-deleted.

### POST `/api/v1/segment_sets/{segment_set_id}/clone_patch_item`

Path params:

| Name | Type | Required |
|---|---|---|
| `segment_set_id` | string | yes |

Request body (`ClonePatchSegmentRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `item_id` | string | yes | - | existing segment item id in source set |
| `patch` | object | yes | - | patch keys below; unspecified keys keep original values |
| `params` | object | no | `{}` | free-form metadata persisted under `segment_set.params.clone_patch` |

`patch` supported keys:

| Key | Type | Required | Notes |
|---|---|---|---|
| `content` | string | no | new segment content |
| `metadata` | object | no | full metadata replacement for patched item |
| `parent_id` | string \| null | no | hierarchy linkage override |
| `level` | integer | no | hierarchy level override |
| `path` | string[] | no | hierarchy path override |
| `type` | string | no | segment type override (for example `text`, `table`) |
| `original_format` | string | no | source-format label override |

`params` expected fields:

- No required keys are enforced.
- Recommended keys for traceability: `reason`, `editor`, `ticket`, `source`, `timestamp`.
- API stores exactly what you send at `segment_set.params.clone_patch`.

Response `200`: `SegmentSetWithItems`

Behavior notes:

- Clones all items from source set, applies patch to target item only, and creates derived set.
- New set stores lineage in `parent_segment_set_version_id` and `input_refs.patched_item_id`.
- Active segment set for same document version is switched to the newly created set.

### POST `/api/v1/segment_sets/{segment_set_id}/enrich`

Path params:

| Name | Type | Required |
|---|---|---|
| `segment_set_id` | string | yes |

Request body (`EnrichSegmentsRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `execution_mode` | string | no | `sync` | `sync` or `async` |
| `llm_provider` | string \| null | no | `null` | overrides default LLM provider |
| `llm_model` | string \| null | no | `null` | overrides default LLM model |
| `llm_temperature` | number \| null | no | `null` | overrides default LLM temperature |
| `params` | object | no | `{}` | free-form enrichment metadata persisted as `enrich_params` |

Behavior notes:

- Requires LLM capability for actual processing.
- `execution_mode=async` enqueues job type `segment_enrich`.
- `params` has no enforced schema; recommended keys: `prompt_variant`, `labels`, `audit`.

Response `200`:

- Sync: `{ "mode": "sync", "segment_set": SegmentSetOut, "items": SegmentItemOut[] }`
- Async: `{ "mode": "async", "job_id": "<id>" }`

### POST `/api/v1/segment_sets/{segment_set_id}/raptor`

Path params:

| Name | Type | Required |
|---|---|---|
| `segment_set_id` | string | yes |

Request body (`RaptorSegmentsRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `execution_mode` | string | no | `async` | `sync` or `async` |
| `max_levels` | integer | no | `3` | RAPTOR hierarchy depth |
| `llm_provider` | string \| null | no | `null` | overrides LLM provider |
| `llm_model` | string \| null | no | `null` | overrides LLM model |
| `llm_temperature` | number \| null | no | `null` | overrides LLM temperature |
| `embedding_provider` | string | no | `openai` | embedding provider for clustering |
| `embedding_model_name` | string \| null | no | `null` | embedding model override |
| `params` | object | no | `{}` | free-form metadata persisted under `raptor_params` |

Behavior notes:

- Requires `FEATURE_ENABLE_RAPTOR=true` and `FEATURE_ENABLE_LLM=true`.
- Requires optional dependency `umap-learn`.
- `execution_mode=async` enqueues job type `segment_raptor`.

Response `200`:

- Sync: `{ "mode": "sync", "segment_set": SegmentSetOut, "items": SegmentItemOut[] }`
- Async: `{ "mode": "async", "job_id": "<id>" }`

### POST `/api/v1/segment_sets/{segment_set_id}/chunk`

Path params:

| Name | Type | Required |
|---|---|---|
| `segment_set_id` | string | yes |

Request body (`ChunkFromSegmentRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `strategy` | string | no | `recursive` | Allowed: `recursive`, `token`, `sentence`, `regex`, `markdown_table`, `semantic` |
| `chunker_params` | object | no | `{}` | strategy-specific parameters below |

`chunker_params` by strategy:

| strategy | Parameter | Type | Required | Default | Notes |
|---|---|---|---|---|---|
| `recursive` | `chunk_size` | integer | no | `4000` | max chars/tokens per chunk by splitter logic |
| `recursive` | `chunk_overlap` | integer | no | `200` | overlap between adjacent chunks |
| `recursive` | `separators` | string[] \| null | no | splitter default | custom separator priority list |
| `token` | `chunk_size` | integer | no | `4000` | token-window size |
| `token` | `chunk_overlap` | integer | no | `200` | token overlap |
| `token` | `model_name` | string | no | `cl100k_base` | token model name |
| `token` | `encoding_name` | string \| null | no | `null` | optional tokenizer encoding |
| `sentence` | `chunk_size` | integer | no | `4000` | chunk size |
| `sentence` | `chunk_overlap` | integer | no | `200` | overlap |
| `sentence` | `language` | string | no | `english` | sentence splitter language |
| `regex` | `pattern` | string | yes | - | Python regex for `re.split`; required |
| `regex` | `chunk_size` | integer | no | `4000` | constructor argument |
| `regex` | `chunk_overlap` | integer | no | `200` | constructor argument |
| `markdown_table` | none | - | - | - | no custom params |
| `semantic` | `embedding_provider` | string \| null | no | provider default | embedding provider |
| `semantic` | `embedding_model_name` | string \| null | no | provider default | embedding model |
| `semantic` | `threshold` | number \| null | no | splitter default | semantic split threshold |
| `semantic` | `threshold_type` | string | no | `fixed` | threshold mode |
| `semantic` | `percentile_threshold` | integer | no | `90` | percentile threshold |
| `semantic` | `window_size` | integer | no | `1` | semantic context window |

Error behavior:

- unsupported strategy -> `400 unsupported_chunk_strategy`
- `strategy=regex` and missing `pattern` -> `400 invalid_chunker_params`

Response `200`: `ChunkSetWithItems`

Behavior notes:

- Existing active chunk sets in project are deactivated before creating the new set.
- Output items are ordered by `position asc`.
- Each emitted chunk has new `item_id` and includes `source_segment_item_id` + `chunk_index` in metadata.

### GET `/api/v1/projects/{project_id}/chunk_sets`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`: `ChunkSetOut[]`

Behavior notes:

- Returns only non-deleted chunk sets for the project.
- Sorted by `created_at desc`.
- `total_items` is computed per chunk set.

### GET `/api/v1/chunk_sets/{chunk_set_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `chunk_set_id` | string | yes |

Query/body params: none.

Response `200`: `ChunkSetWithItems`

Behavior notes:

- Returns chunk set plus all chunk items ordered by `position asc`.
- Returns `404 chunk_set_not_found` when missing or soft-deleted.

### POST `/api/v1/chunk_sets/{chunk_set_id}/clone_patch_item`

Path params:

| Name | Type | Required |
|---|---|---|
| `chunk_set_id` | string | yes |

Request body (`ClonePatchChunkRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `item_id` | string | yes | - | existing chunk item id in source set |
| `patch` | object | yes | - | patch keys below; unspecified keys keep original values |
| `params` | object | no | `{}` | free-form metadata persisted under `chunk_set.params.clone_patch` |

`patch` supported keys:

| Key | Type | Required | Notes |
|---|---|---|---|
| `content` | string | no | new chunk content |
| `metadata` | object | no | metadata replacement for patched item |
| `parent_id` | string \| null | no | hierarchy linkage override |
| `level` | integer | no | hierarchy level override |
| `path` | string[] | no | hierarchy path override |
| `type` | string | no | type override |
| `original_format` | string | no | source-format label override |

`params` expected fields:

- No required keys are enforced.
- Recommended keys: `reason`, `editor`, `ticket`, `source`, `timestamp`.
- API stores exactly what you send at `chunk_set.params.clone_patch`.

Response `200`: `ChunkSetWithItems`

Behavior notes:

- Clones all chunk items, patches target item, and creates derived chunk set version.
- Lineage saved in `parent_chunk_set_version_id` and `input_refs.patched_item_id`.
- Project active chunk set is switched to newly created set.

### POST `/api/v1/projects/{project_id}/indexes`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Request body (`CreateIndexRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `name` | string | yes | - | logical index name |
| `provider` | string | no | `qdrant` | Allowed: `qdrant`, `faiss`, `chroma`, `postgres` |
| `index_type` | string | no | `chunk_vectors` | metadata label; build logic does not branch on this |
| `config` | object | no | `{}` | provider/build config keys below |
| `params` | object | no | `{}` | free-form index metadata |

`config` keys:

| Key | Type | Scope | Required | Default | Notes |
|---|---|---|---|---|---|
| `embedding_provider` | string | all providers | no | `openai` | embedding provider |
| `embedding_model_name` | string \| null | all providers | no | `null` | embedding model |
| `collection_name` | string | qdrant/chroma/postgres | no | generated | backend collection name |
| `faiss_local_dir` | string | faiss | no | generated after build | usually produced by build |
| `chroma_persist_directory` | string | chroma | no | generated | disk path for chroma data |
| `connection` | string | postgres | no | `VECTOR_POSTGRES_CONNECTION` | PGVector connection string |

`params` expected fields:

- No required keys are enforced.
- Recommended keys: `owner`, `purpose`, `tags`, `retention`.

Response `200`: `IndexOut`

Behavior notes:

- Index row is created with initial status `created`.
- Provider validation is strict (`qdrant|faiss|chroma|postgres`), otherwise `400 invalid_index_provider`.

### GET `/api/v1/projects/{project_id}/indexes`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`: `IndexOut[]`

Behavior notes:

- Returns only non-deleted indexes for project.
- Sorted by `created_at desc`.

### GET `/api/v1/indexes/{index_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `index_id` | string | yes |

Query/body params: none.

Response `200`: `IndexOut`

Behavior notes:

- Returns `404 index_not_found` when missing or soft-deleted.

### POST `/api/v1/indexes/{index_id}/builds`

Path params:

| Name | Type | Required |
|---|---|---|
| `index_id` | string | yes |

Request body (`CreateIndexBuildRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `chunk_set_version_id` | string | yes | - | source chunk set for build |
| `params` | object | no | `{}` | free-form build metadata persisted on build |
| `execution_mode` | string | no | `sync` | `sync` or `async` |

`params` expected fields:

- No required keys are enforced by API.
- Recommended keys: `trigger`, `note`, `requested_by`.

Response `200`:

- Sync: `{ "mode": "sync", "build": IndexBuildOut }`
- Async: `{ "mode": "async", "job_id": "<id>", "build": IndexBuildOut }`

Behavior notes:

- Build is created first with status `queued`.
- Sync mode executes build immediately and may fail with provider/dependency/config errors.
- Async mode enqueues job type `index_build`.

### GET `/api/v1/indexes/{index_id}/builds`

Path params:

| Name | Type | Required |
|---|---|---|
| `index_id` | string | yes |

Query/body params: none.

Response `200`: `IndexBuildOut[]`

Behavior notes:

- Returns non-deleted builds for index.
- Sorted by `created_at desc`.

### GET `/api/v1/index_builds/{build_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `build_id` | string | yes |

Query/body params: none.

Response `200`: `IndexBuildOut`

Behavior notes:

- Returns `404 index_build_not_found` when missing or soft-deleted.

### POST `/api/v1/projects/{project_id}/graph/builds`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Request body (`CreateGraphBuildRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `source_type` | string | no | `segment_set` | `segment_set` or `chunk_set` |
| `source_id` | string | yes | - | id of source artifact matching `source_type` |
| `backend` | string \| null | no | `null` | `neo4j` or `networkx`; `null` means service default |
| `extract_entities` | boolean | no | `true` | run entity extraction stage |
| `detect_communities` | boolean | no | `false` | run community detection stage |
| `summarize_communities` | boolean | no | `false` | run community summarization stage |
| `llm_provider` | string \| null | no | `null` | LLM provider override |
| `llm_model` | string \| null | no | `null` | LLM model override |
| `llm_temperature` | number \| null | no | `null` | LLM temperature override |
| `search_depth` | integer | no | `1` | local graph retrieval depth metadata |
| `params` | object | no | `{}` | extra free-form params merged into persisted build params |
| `execution_mode` | string | no | `async` | `sync` or `async` |

`params` expected fields:

- Required for graph retrieval: `index_build_id` (must reference a succeeded index build in the same project).
- Keys in `params` are merged into build parameters; collisions can override same-name defaults.
- Optional metadata keys: `label`, `run_reason`, `owner`.

Response `200`:

- Sync: `{ "mode": "sync", "build": GraphBuildOut }`
- Async: `{ "mode": "async", "job_id": "<id>", "build": GraphBuildOut }`

Behavior notes:

- Requires graph capability flag.
- Sync mode runs graph pipeline immediately.
- Async mode enqueues job type `graph_build`.

### GET `/api/v1/projects/{project_id}/graph/builds`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`: `GraphBuildOut[]`

Behavior notes:

- Returns only non-deleted graph builds for project.
- Sorted by `created_at desc`.

### GET `/api/v1/graph_builds/{graph_build_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `graph_build_id` | string | yes |

Query/body params: none.

Response `200`: `GraphBuildOut`

Behavior notes:

- Returns `404 graph_build_not_found` when missing or soft-deleted.

### POST `/api/v1/projects/{project_id}/retrieve`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Request body (`RetrieveRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `query` | string | yes | - | retrieval query text |
| `target` | string | no | `chunk_set` | `chunk_set`, `segment_set`, `index_build`, `graph_build` |
| `target_id` | string \| null | no | `null` | target artifact id; requirement depends on strategy/target |
| `strategy` | object | yes | - | discriminated union by `strategy.type`, detailed below |
| `persist` | boolean | no | `false` | persist retrieval run artifact |
| `limit` | integer | no | `20` | page size; clamped to `1..200` |
| `cursor` | string \| null | no | `null` | base64 offset cursor |

`strategy` by `type`:

| strategy.type | Field | Type | Required | Default | Notes |
|---|---|---|---|---|---|
| `vector` | `k` | int | no | `10` | top-k |
| `vector` | `search_type` | string | no | `similarity` | strict enum: `similarity`, `similarity_score_threshold`, `mmr` |
| `vector` | `score_threshold` | float \| null | no | `null` | applied by rag-lib vector retriever |
| `bm25` | `k` | int | no | `10` | top-k |
| `regex` | `pattern` | string | yes | - | regex query pattern |
| `fuzzy` | `threshold` | int | no | `80` | fuzzy match threshold |
| `ensemble` | `sources` | array | no | `[]` | source list (`bm25`, `regex`, `fuzzy`, `vector`) |
| `ensemble` | `weights` | float[] \| null | no | `null` | optional blend weights |
| `rerank` | `base` | object | yes | - | base strategy spec |
| `rerank` | `model_name` | string | no | `BAAI/bge-reranker-base` | reranker model |
| `rerank` | `top_n` | int | no | `5` | final reranked size |
| `rerank` | `device` | string | no | `cpu` | runtime device |
| `dual_storage` | `vector_search` | object | no | `{}` | supports key `k` for vector recall size |
| `dual_storage` | `id_key` | string | no | `parent_id` | must match index build `doc_store.id_key` |
| `graph` | `graph_build_id` | string | yes | - | graph build identifier |
| `graph` | `mode` | string | no | `hybrid` | `local`, `global`, `hybrid`, `mix` |
| `graph` | `search_depth` | int | no | `1` | build metadata; retrieval depth controlled by graph config |
| `graph_hybrid` | `graph_build_id` | string | yes | - | graph build identifier |
| `graph_hybrid` | `mode` | string | no | `hybrid` | `local`, `global`, `hybrid`, `mix` |
| `graph_hybrid` | `search_depth` | int | no | `1` | build metadata; retrieval depth controlled by graph config |
| `graph_hybrid` | `vector` | object | no | `{"k":10,"search_type":"similarity","score_threshold":null}` | optional vector side config |
| `graph_hybrid` | `weights` | float[] \| null | no | `null` | blend weights `[vector, graph]` |

Nested object details used by retrieval implementation:

| Object path | Field | Type | Required | Default | Notes |
|---|---|---|---|---|---|
| `strategy.ensemble.sources[]` | `type` | string | yes | - | supported: `bm25`, `regex`, `fuzzy` |
| `strategy.ensemble.sources[]` | `k` | int | no | `8` | used when source type is `bm25` |
| `strategy.ensemble.sources[]` | `threshold` | int | no | `75` | used when source type is `fuzzy` |
| `strategy.rerank.base` | `type` | string | no | `bm25` | base retrieval type |
| `strategy.rerank.base` | `k` | int | no | `20` | used by bm25 base |
| `strategy.rerank.base` | `pattern` | string | no | query-based | used by regex base |
| `strategy.rerank.base` | `threshold` | int | no | `75` | used by fuzzy base |
| `strategy.dual_storage.vector_search` | `k` | int | no | `10` | vector recall size |
| `strategy.graph_hybrid.vector` | `k` | int | no | `10` | vector top-k |
| `strategy.graph_hybrid.vector` | `search_type` | string | no | `similarity` | strict enum: `similarity`, `similarity_score_threshold`, `mmr` |
| `strategy.graph_hybrid.vector` | `score_threshold` | float \| null | no | `null` | passed to vector retriever |

Target/strategy requirements:

| strategy/target | `target` requirement | `target_id` requirement |
|---|---|---|
| `vector` | must be `index_build` | required |
| `dual_storage` | must be `index_build` | required |
| `bm25` / `regex` / `fuzzy` / `ensemble` | `chunk_set` or `segment_set` | optional (latest active used when omitted) |
| `rerank` with vector base | same as vector | same as vector |
| `graph` / `graph_hybrid` | must be `graph_build` | required; graph build params must include `index_build_id` |
| `graph` | any target accepted, graph id comes from strategy | `target_id` not used by graph path |
| `graph_hybrid` | vector side runs only when `target=index_build` and `target_id` present | optional unless vector side is intended |

Response `200`: `RetrieveResponse`

Behavior notes:

- Results are paged with offset-based cursor (`limit`, `cursor`).
- `persist=true` stores retrieval run row and artifact payload; `run_id` is returned.
- Invalid cursor is treated as offset `0`.

### GET `/api/v1/projects/{project_id}/retrieval_runs`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`: `RetrievalRunOut[]`

Behavior notes:

- Returns non-deleted retrieval runs for project.
- Sorted by `created_at desc`.

### GET `/api/v1/retrieval_runs/{run_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `run_id` | string | yes |

Query/body params: none.

Response `200`: `RetrievalRunOut`

Behavior notes:

- Returns `404 retrieval_run_not_found` when missing or soft-deleted.

### DELETE `/api/v1/retrieval_runs/{run_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `run_id` | string | yes |

Query/body params: none.

Response `200`:

| Field | Type |
|---|---|
| `ok` | boolean |
| `run_id` | string |

Behavior notes:

- Soft-deletes retrieval run (`is_deleted=true`).

### GET `/api/v1/projects/{project_id}/jobs`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query/body params: none.

Response `200`: `JobOut[]`

Behavior notes:

- Returns jobs for project (all statuses).
- Sorted by `created_at desc`.

### GET `/api/v1/jobs/{job_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `job_id` | string | yes |

Query/body params: none.

Response `200`: `JobOut`

Behavior notes:

- Returns `404 job_not_found` when missing.

### GET `/api/v1/admin/jobs`

| Parameter location | Parameters |
|---|---|
| path | none |
| query | none |
| body | none |

Response `200`: `JobOut[]`

Behavior notes:

- Returns all jobs across projects.
- Sorted by `created_at desc`.

### POST `/api/v1/projects/{project_id}/pipeline/file`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Multipart form fields:

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `file` | binary file | yes | - | uploaded source file |
| `loader_type` | string \| null | no | `null` | optional loader override for load stage |
| `loader_params_json` | string \| null | no | `null` | valid JSON string; parsed to load-stage `loader_params` |
| `split_strategy` | string | yes | - | segment split strategy |
| `splitter_params_json` | string \| null | no | `null` | valid JSON string; parsed to split-stage `splitter_params` |
| `create_index` | boolean | no | `false` | whether to attempt index build stage |
| `index_id` | string \| null | no | `null` | required to actually build index when `create_index=true` |
| `index_params_json` | string \| null | no | `null` | valid JSON string; parsed to object and passed as index build `params` |
| `execution_mode` | string | no | `sync` | `sync` or `async` |

JSON-form field expectations:

- `loader_params_json`: same keys as load-stage `loader_params`.
- `splitter_params_json`: same keys as split strategy options.
- `index_params_json`: free-form object persisted on index build record; no enforced keys.

Response `200`: `PipelineResponse`

Behavior notes:

- `execution_mode=async`: returns immediately with `status="queued"` and `job_id`; artifact ids are `null`.
- `execution_mode=sync`: runs full pipeline and returns concrete ids with `status="succeeded"`.
- Pipeline lineage includes `document_set_version_id` between document upload and segment generation.
- Index build stage runs only when `create_index=true` and `index_id` is provided.

### GET `/api/v1/projects/{project_id}/artifacts`

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query params:

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `limit` | integer | no | settings default (`20`) | `>=1`; clamped to max `200` |
| `cursor` | string \| null | no | `null` | base64 offset cursor; invalid cursor treated as offset `0` |

Request body: none.

Response `200`:

| Field | Type | Notes |
|---|---|---|
| `items` | `ArtifactOut[]` | unified artifact stream |
| `next_cursor` | string \| null | cursor for next page |
| `has_more` | boolean | pagination flag |
| `total` | integer | total items before slicing |

Behavior notes:

- Includes artifact kinds: `document`, `document_version`, `segment_set`, `chunk_set`, `index`, `index_build`, `graph_build`, `retrieval_run`.
- Sorted by artifact `created_at desc` across all kinds.
- `items[].metadata` keys vary by artifact kind:
  - `document`: `filename`
  - `document_version`: `document_id`, `status`
  - `segment_set`: `document_version_id`, `is_active`
  - `chunk_set`: `segment_set_version_id`, `is_active`
  - `index`: `name`, `provider`
  - `index_build`: `index_id`, `status`, `is_active`
  - `graph_build`: `source_type`, `source_id`, `backend`, `status`
  - `retrieval_run`: `strategy`, `target_type`

### DELETE `/api/v1/artifacts/{artifact_id}`

Path params:

| Name | Type | Required |
|---|---|---|
| `artifact_id` | string | yes |

Request body (`SoftDeleteRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `reason` | string \| null | no | `null` | audit reason text persisted in delete log |

Response `200`: `DeleteResponse`

Behavior notes:

- Performs soft delete only (`is_deleted=true`) and writes delete audit row.
- Returns `404 artifact_not_found` when id does not resolve.

### POST `/api/v1/artifacts/{artifact_id}/restore`

Path params:

| Name | Type | Required |
|---|---|---|
| `artifact_id` | string | yes |

Query/body params: none.

Response `200`: `RestoreResponse`

Behavior notes:

- Restores previously soft-deleted artifact by setting `is_deleted=false`.
- Updates most recent unresolved delete audit record with `restored_at` when present.

### POST `/api/v1/tables/summarize`

Path/query params: none.

Request body (`TableSummarizeRequest`):

| Field | Type | Required | Default | Constraints / behavior |
|---|---|---|---|---|
| `markdown_table` | string | yes | - | min length `1`; markdown table text |
| `summarizer` | object | no | `{"type":"mock"}` | summarizer config |

`summarizer` nested fields:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `type` | string | no | `mock` | `mock` or `llm` |
| `llm_provider` | string \| null | no | `null` | used with `type=llm` |
| `model` | string \| null | no | `null` | used with `type=llm` |
| `temperature` | number \| null | no | `null` | used with `type=llm` |

Behavior notes:

- `type=llm` requires `FEATURE_ENABLE_LLM=true` and valid provider credentials.

Response `200`: `TableSummarizeResponse`

| Field | Type | Notes |
|---|---|---|
| `summary` | string | generated summary text |
| `summarizer_type` | string | `mock` or `llm` |

## Segment and Chunk Details (Historical Notes)

The canonical ingestion contract is now documented in:
- `docs/rag_lib_load_split_contract.md`

The subsection below is retained as historical implementation detail and is not the source of truth for current load endpoints.

## Legacy segment loader notes

| Loader `loader_type` | Supported params (`loader_params`) | Notes |
|---|---|---|
| `pdf` | `backend` | Delegates to `rag_lib.loaders.pdf.PDFLoader` |
| `miner_u` | `parse_mode`, `backend`, `lang`, `server_url`, `start_page`, `end_page`, `parse_formula`, `parse_table`, `device`, `vram`, `source`, `timeout_seconds`, `keep_temp_artifacts` | Strict MinerU behavior; no API fallback to PDF loader |
| `docx` | `regex_patterns`, `exclude_patterns`, `include_parent_content` (default `true`) | Structured loader |
| `csv` | `chunk_size` | CSV loader |
| `excel` | none | Excel loader |
| `json` | `jq_schema` (default `"."`) | JSON loader |
| `qa` | none | QA loader |
| `table` | `mode` (default `"row"`), `group_by` | table rows/groups |
| `regex` | `patterns` (required), `exclude_patterns`, `include_parent_content` | Delegates to `rag_lib.loaders.regex.RegexHierarchyLoader` |

Important behavior:

- If `source_text` is provided, service returns exactly one text segment and ignores file loader execution.
- Unsupported loader without `source_text` returns `400 unsupported_loader`.

### Regex Loader Contract (`loader_type=regex`)

This section describes the exact runtime behavior of `rag_lib.loaders.regex.RegexHierarchyLoader` as used by this API.

`loader_params` fields:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `patterns` | array | yes | - | accepted shapes: `[[level:int, pattern:str], ...]` or `[{"level": int, "pattern": str \| string[]}, ...]` |
| `exclude_patterns` | string[] | no | `[]` | lines matching any pattern are skipped from hierarchy matching |
| `include_parent_content` | bool \| int | no | `false` | content concatenation mode, see table below |

`include_parent_content` behavior:

| Value | Behavior |
|---|---|
| `false` | child segment content is only its own matched block |
| `true` | child segment content is prefixed with full ancestor content chain |
| `N` (int) | ancestor content is prefixed only when parent level is `>= N` |

Matching semantics:

- Processing is line-based (`splitlines`).
- Pattern evaluation is ordered; first matching pattern wins.
- Matching uses Python regex `search` (not `match`) for this loader.
- `metadata.title` source:
  - first capture group (`group(1)`) when present
  - else trailing text after the matched portion
  - else full line text

Hierarchy semantics in output:

- `level` equals the configured pattern level.
- `path` contains ancestor titles only (current title is not appended to its own path).
- `parent_id` is typically `null` for regex-loader-produced segments.
- A level-0 root/preamble segment is emitted when pre-heading content exists and is non-empty after trimming.

Validation/error behavior:

- Missing or empty `patterns` returns `400 invalid_loader_params`.

Example request payload:

```json
{
  "loader_type": "regex",
  "loader_params": {
    "patterns": [
      [1, "^Section\\s+(\\d+):"],
      [2, "^Subsection\\s+(\\d+\\.\\d+):"]
    ],
    "exclude_patterns": ["^\\s*#"],
    "include_parent_content": false
  }
}
```

Example source text:

```text
Overview
Section 1: Access
Access rules text.
Subsection 1.1: Passwords
Password details.
Section 2: Audit
Audit trail text.
```

Observed output shape (trimmed):

| content (trimmed) | level | path | metadata.title | parent_id |
|---|---:|---|---|---|
| `Overview` | 0 | `[]` | `ROOT` | `null` |
| `Section 1: Access ...` | 1 | `[]` | `1` | `null` |
| `Subsection 1.1: Passwords ...` | 2 | `["1"]` | `1.1` | `null` |
| `Section 2: Audit ...` | 1 | `[]` | `2` | `null` |

### DOCX + `regex_patterns` hierarchy behavior (`loader_type=docx`)

`loader_params` fields relevant to regex handling:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `regex_patterns` | array | no | `null` | accepted tuple/dict shapes: `[[level, pattern], ...]` or `{"level":..., "pattern": ...}` |
| `exclude_patterns` | string[] | no | `[]` | forwarded to regex-based post-splitting stage |
| `include_parent_content` | bool | no | `true` | forwarded to regex-based post-splitting stage |

Heading detection order in DOCX loader:

1. Word paragraph style (`Heading1`, `Heading2`, ...) is checked first.
2. If style is not a heading, regex-based section detection is checked next.
3. For docx regex heading detection, regex uses Python `match` (start of string), so anchors like `^` are recommended.

Post-splitting behavior when `regex_patterns` is provided:

- Text segments with `level > 0` are post-processed by regex hierarchy splitting.
- Sub-segment remapping rules are applied:
  - when sub-level is `0`: sub-segment inherits original segment `level`, `path`, and `parent_id`
  - when sub-level is `> 0`: sub-segment path is prefixed with the original segment title context

Runtime caveat for frontend tree building:

- In `docx + regex_patterns` mode, `parent_id` can be less reliable for strict tree reconstruction.
- Prefer deterministic rendering from `level + path + metadata.title`, and treat `parent_id` as optional linkage metadata.

Example 1 (style-based headings):

```json
{
  "loader_type": "docx",
  "loader_params": {
    "include_parent_content": true
  }
}
```

Example 2 (regex-only headings for non-styled paragraphs):

```json
{
  "loader_type": "docx",
  "loader_params": {
    "regex_patterns": [
      [1, "^Section\\s+(\\d+):"],
      [2, "^Subsection\\s+(\\d+\\.\\d+):"]
    ],
    "exclude_patterns": ["^DRAFT\\b"],
    "include_parent_content": false
  }
}
```

## Segment item typing

Returned `SegmentItemOut.type` enum:

- `text`
- `table`
- `image`
- `audio`
- `code`
- `other`

## Chunk strategies

Used by `POST /api/v1/segment_sets/{segment_set_id}/chunk`.

| Strategy | Required params | Optional params | Notes |
|---|---|---|---|
| `recursive` | none | `chunk_size` (4000), `chunk_overlap` (200), `separators` | Recursive character splitter |
| `token` | none | `chunk_size` (4000), `chunk_overlap` (200), `model_name` (`cl100k_base`), `encoding_name` | Token-aware splitter |
| `sentence` | none | `chunk_size` (4000), `chunk_overlap` (200), `language` (`english`) | Sentence splitter |
| `regex` | `pattern` | `chunk_size` (4000), `chunk_overlap` (200) | Regex splitter, missing pattern -> `400 invalid_chunker_params` |
| `markdown_table` | none | none | Table-oriented markdown splitter |
| `semantic` | none | `embedding_provider`, `embedding_model_name`, `threshold`, `threshold_type` (`fixed`), `percentile_threshold` (90), `window_size` (1) | Embedding-based semantic splitter |

Chunk output behavior:

- Empty/whitespace-only chunks are discarded.
- Each emitted chunk gets fresh `item_id`.
- Metadata automatically includes:
  - `source_segment_item_id`
  - `chunk_index`
  - plus any metadata emitted by chunker

### Regex Chunker Contract (`strategy=regex`)

This section describes exact runtime behavior of `rag_lib.chunkers.regex.RegexSplitter` used by this API.

`chunker_params` fields:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `pattern` | string | yes | - | Python regex passed to `re.split` |
| `chunk_size` | int | no | `4000` | accepted by API and forwarded to splitter constructor |
| `chunk_overlap` | int | no | `200` | accepted by API and forwarded to splitter constructor |

Regex split semantics:

- Splitting uses Python `re.split(pattern, text)`.
- Capturing groups in `pattern` are returned as standalone chunks.
- Missing `pattern` returns `400 invalid_chunker_params`.

Pattern examples:

| Goal | Pattern | Example output notes |
|---|---|---|
| Delimiter drop (recommended) | `r"\.\s+"` | sentence delimiter removed from output chunks |
| Keep section header at chunk start (recommended) | `r"(?=Section\s+\d+:)"` | section label remains at start of each chunk |
| Preserve punctuation when splitting between sections (recommended) | `r"(?<=\.)\s+(?=Section\s+\d+:)"` | period kept on previous chunk |
| Capturing-group caveat (generally avoid unless intended) | `r"(\.\s+)"` | delimiter capture appears as additional chunk entries |

Example split contrast for `text = "Section 1: A. Section 2: B."`:

- `pattern = r"(\.\s+)"` -> `["Section 1: A", ". ", "Section 2: B."]` (extra delimiter chunk)
- `pattern = r"\.\s+"` -> `["Section 1: A", "Section 2: B."]` (recommended)

Hierarchy propagation during regex chunking:

- Chunking does not recompute hierarchy.
- Each emitted chunk inherits source segment `parent_id`, `level`, and `path`.
- Metadata always includes:
  - `source_segment_item_id`
  - `chunk_index`

### Frontend Hierarchy Interpretation Rules

> Use `level`, `path`, and `metadata.title` as primary hierarchy signals in UI.
>
> Treat `parent_id` as optional linkage metadata, not as the only tree key.
>
> Handle root/preamble segments (`level=0`) explicitly.
>
> Preserve server ordering via `position`.

## Versioning/active semantics for segments and chunks

- New segment set creation deactivates active sets for the same `document_version_id`.
- Segment clone-patch creates a child set with `parent_segment_set_version_id` and deactivates prior active set for same doc version.
- New chunk set creation deactivates active chunk sets for the project.
- Chunk clone-patch creates a child set with `parent_chunk_set_version_id` and deactivates prior active project chunk sets.

## Indexes (Strategies, Providers, Types, Options)

## Index providers

| Provider | Build behavior | Retrieval behavior |
|---|---|---|
| `qdrant` | Uses `rag_lib.vectors.factory.create_vector_store` + `rag_lib.core.Indexer` | Retrieval uses the same rag-lib factory path |
| `faiss` | Uses `rag_lib.vectors.factory.create_vector_store` + `rag_lib.core.Indexer`, then persists local artifact | Retrieval loads persisted FAISS artifact after rag-lib factory initialization |
| `chroma` | Uses `rag_lib.vectors.factory.create_vector_store` + `rag_lib.core.Indexer` | Retrieval uses the same rag-lib factory path |
| `postgres` | Uses `rag_lib.vectors.factory.create_vector_store` + `rag_lib.core.Indexer` | Retrieval uses the same rag-lib factory path |

Any other provider returns `501 provider_unsupported` for build/retrieval execution.

## `index_type`

Default is `chunk_vectors`. It is persisted as metadata; current build logic does not branch on this field.

## Index config options used by implementation

| Config field | Scope | Default | Notes |
|---|---|---|---|
| `embedding_provider` | all provider builds + vector retrieval | `openai` | forwarded to rag-lib embedding factory |
| `embedding_model_name` | all providers | `null` | forwarded to embedding factory |
| `collection_name` | qdrant/chroma/postgres | generated `rag_api_<project_id>_<index_id>` | collection/table name used by rag-lib factory |
| `faiss_local_dir` | faiss | generated during build | populated after successful FAISS build |
| `connection` | postgres | from `VECTOR_POSTGRES_CONNECTION` | PGVector connection string |

## Build statuses and lifecycle

Observed statuses:

- `queued`
- `running`
- `succeeded`
- `failed`

Index status transitions:

- initial `created`
- on successful build `ready`

## Retrieval Strategies (Types/Options)

`RetrieveRequest.strategy` is a discriminated union by `type`.

### `vector`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | literal `"vector"` | - | required discriminator |
| `k` | int | `10` | top-k hits |
| `search_type` | string | `similarity` | strict enum: `similarity`, `similarity_score_threshold`, `mmr` |
| `score_threshold` | float \| null | `null` | passed to rag-lib vector retriever |

Constraints:

- Requires `target="index_build"` and non-null `target_id`.

### `bm25`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | literal `"bm25"` | - | discriminator |
| `k` | int | `10` | top-k |

### `regex`

| Field | Type | Default |
|---|---|---|
| `type` | literal `"regex"` | - |
| `pattern` | string | - |

### `fuzzy`

| Field | Type | Default |
|---|---|---|
| `type` | literal `"fuzzy"` | - |
| `threshold` | int | `80` |

### `ensemble`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | literal `"ensemble"` | - | discriminator |
| `sources` | array | `[]` | each source typically `bm25`, `regex`, or `fuzzy` |
| `weights` | number[] \| null | `null` | optional blend weights |

If `sources` is empty, service uses default ensemble composition (BM25 + regex + fuzzy).

### `rerank`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | literal `"rerank"` | - | discriminator |
| `base` | object | - | base strategy spec (`bm25`/`regex`/`fuzzy`/`vector`) |
| `model_name` | string | `BAAI/bge-reranker-base` | reranker model |
| `top_n` | int | `5` | reranked output size |
| `device` | string | `cpu` | runtime device |

If `base.type == "vector"`, same target constraints as vector apply (`target=index_build`, `target_id` required).

### `dual_storage`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | literal `"dual_storage"` | - | discriminator |
| `vector_search` | object | `{}` | `k` is used for vector recall |
| `id_key` | string | `parent_id` | must match index build `doc_store.id_key` |

Constraints:

- Requires `target="index_build"` and non-null `target_id`.
- Supported for all currently supported vector index providers (`qdrant`, `faiss`, `chroma`, `postgres`) when build includes `doc_store`.

## Retrieval target semantics

| Target | `target_id` required? | Data source |
|---|---|---|
| `chunk_set` | no (optional) | chunk items (if missing, latest active chunk set is used) |
| `segment_set` | no (optional) | segment items (if missing, latest active segment set is used) |
| `index_build` | yes for vector/dual | vector index build + provider-specific backend |
| `graph_build` | yes for graph strategy fields | graph build used by `graph` and `graph_hybrid` strategies |

## Async Processing Model

Async modes create `Job` rows and run Celery tasks:

- index build async:
  - endpoint: `POST /api/v1/indexes/{index_id}/builds` with `execution_mode="async"`
  - task: `run_index_build`
  - job type: `index_build`
- pipeline async:
  - endpoint: `POST /api/v1/projects/{project_id}/pipeline/file` with `execution_mode="async"`
  - task: `run_pipeline`
  - job type: `pipeline`
- graph build async:
  - endpoint: `POST /api/v1/projects/{project_id}/graph/builds` with `execution_mode="async"`
  - task: `run_graph_build`
  - job type: `graph_build`
- segment enrich async:
  - endpoint: `POST /api/v1/segment_sets/{segment_set_id}/enrich` with `execution_mode="async"`
  - task: `run_segment_enrich`
  - job type: `segment_enrich`
- segment raptor async:
  - endpoint: `POST /api/v1/segment_sets/{segment_set_id}/raptor` with `execution_mode="async"`
  - task: `run_segment_raptor`
  - job type: `segment_raptor`

Job statuses:

- `queued`
- `running`
- `succeeded`
- `failed`

## Artifact Soft Delete Coverage

Soft delete/restore supports these artifact kinds:

- `document`
- `document_version`
- `segment_set`
- `chunk_set`
- `index`
- `index_build`
- `graph_build`
- `retrieval_run`

Soft delete only toggles DB flags and tracks delete/restore audit rows. It does not remove object-store files.

## Response Object Schemas (Returned Values)

All timestamps are RFC3339/ISO-8601 datetime strings.

## `ProjectOut`

| Field | Type |
|---|---|
| `project_id` | string |
| `name` | string |
| `description` | string \| null |
| `settings` | object (`default_retrieval_preset`, `default_chunking_preset`, `extra`) |
| `created_at` | datetime |
| `updated_at` | datetime |

## `DocumentOut`

| Field | Type |
|---|---|
| `document_id` | string |
| `project_id` | string |
| `filename` | string |
| `mime` | string |
| `storage_uri` | string |
| `metadata` | object |
| `is_deleted` | boolean |
| `created_at` | datetime |
| `updated_at` | datetime |

## `DocumentVersionOut`

| Field | Type |
|---|---|
| `version_id` | string |
| `document_id` | string |
| `content_hash` | string |
| `parser_params` | object |
| `params` | object |
| `input_refs` | object |
| `artifact_uri` | string \| null |
| `producer_type` | string |
| `producer_version` | string |
| `status` | string |
| `is_active` | boolean |
| `is_deleted` | boolean |
| `created_at` | datetime |

## `SegmentSetOut`

| Field | Type |
|---|---|
| `segment_set_version_id` | string |
| `project_id` | string |
| `document_version_id` | string \| null |
| `parent_segment_set_version_id` | string \| null |
| `params` | object |
| `input_refs` | object |
| `artifact_uri` | string \| null |
| `producer_type` | string |
| `producer_version` | string |
| `is_active` | boolean |
| `is_deleted` | boolean |
| `created_at` | datetime |
| `total_items` | integer |

## `SegmentItemOut`

| Field | Type |
|---|---|
| `item_id` | string |
| `position` | integer |
| `content` | string |
| `metadata` | object |
| `parent_id` | string \| null |
| `level` | integer |
| `path` | string[] |
| `type` | enum (`text`, `table`, `image`, `audio`, `code`, `other`) |
| `original_format` | string |

## `SegmentSetWithItems`

| Field | Type |
|---|---|
| `segment_set` | `SegmentSetOut` |
| `items` | `SegmentItemOut[]` |

## `ChunkSetOut`

| Field | Type |
|---|---|
| `chunk_set_version_id` | string |
| `project_id` | string |
| `segment_set_version_id` | string |
| `parent_chunk_set_version_id` | string \| null |
| `params` | object |
| `input_refs` | object |
| `artifact_uri` | string \| null |
| `producer_type` | string |
| `producer_version` | string |
| `is_active` | boolean |
| `is_deleted` | boolean |
| `created_at` | datetime |
| `total_items` | integer |

## `ChunkItemOut`

| Field | Type |
|---|---|
| `item_id` | string |
| `position` | integer |
| `content` | string |
| `metadata` | object |
| `parent_id` | string \| null |
| `level` | integer |
| `path` | string[] |
| `type` | string |
| `original_format` | string |

## `ChunkSetWithItems`

| Field | Type |
|---|---|
| `chunk_set` | `ChunkSetOut` |
| `items` | `ChunkItemOut[]` |

## `IndexOut`

| Field | Type |
|---|---|
| `index_id` | string |
| `project_id` | string |
| `name` | string |
| `provider` | string |
| `index_type` | string |
| `config` | object |
| `params` | object |
| `status` | string |
| `is_deleted` | boolean |
| `created_at` | datetime |
| `updated_at` | datetime |

## `IndexBuildOut`

| Field | Type |
|---|---|
| `build_id` | string |
| `index_id` | string |
| `project_id` | string |
| `chunk_set_version_id` | string |
| `params` | object |
| `input_refs` | object |
| `artifact_uri` | string \| null |
| `status` | string |
| `producer_type` | string |
| `producer_version` | string |
| `is_active` | boolean |
| `is_deleted` | boolean |
| `created_at` | datetime |
| `updated_at` | datetime |

## `RetrievedDocument`

| Field | Type |
|---|---|
| `page_content` | string |
| `metadata` | object |
| `score` | number \| null |

## `RetrieveResponse`

| Field | Type |
|---|---|
| `items` | `RetrievedDocument[]` |
| `next_cursor` | string \| null |
| `has_more` | boolean |
| `strategy` | string |
| `target` | string |
| `target_id` | string \| null |
| `total` | integer |
| `run_id` | string \| null |

## `RetrievalRunOut`

| Field | Type |
|---|---|
| `run_id` | string |
| `project_id` | string |
| `strategy` | string |
| `query` | string |
| `target_type` | string |
| `target_id` | string \| null |
| `params` | object |
| `results` | object |
| `artifact_uri` | string \| null |
| `is_deleted` | boolean |
| `created_at` | datetime |

## `JobOut`

| Field | Type |
|---|---|
| `job_id` | string |
| `project_id` | string \| null |
| `job_type` | string |
| `status` | string |
| `payload` | object |
| `result` | object |
| `error_message` | string \| null |
| `created_at` | datetime |
| `updated_at` | datetime |

## `PipelineResponse`

| Field | Type |
|---|---|
| `project_id` | string |
| `document_id` | string |
| `document_version_id` | string |
| `document_set_version_id` | string |
| `segment_set_version_id` | string |
| `index_build_id` | string \| null |
| `job_id` | string \| null |
| `status` | string |

## `ArtifactOut`

| Field | Type |
|---|---|
| `artifact_kind` | string |
| `artifact_id` | string |
| `project_id` | string |
| `created_at` | datetime |
| `is_deleted` | boolean |
| `metadata` | object |

## `DeleteResponse`

| Field | Type |
|---|---|
| `ok` | boolean |
| `artifact_kind` | string |
| `artifact_id` | string |
| `deleted_at` | datetime |

## `RestoreResponse`

| Field | Type |
|---|---|
| `ok` | boolean |
| `artifact_kind` | string |
| `artifact_id` | string |
| `restored_at` | datetime |

## Advanced Capability Endpoints

- `POST /api/v1/tables/summarize`
- `POST /api/v1/projects/{project_id}/graph/builds`
- `GET /api/v1/projects/{project_id}/graph/builds`
- `GET /api/v1/graph_builds/{graph_build_id}`
- `POST /api/v1/segment_sets/{segment_set_id}/enrich`
- `POST /api/v1/segment_sets/{segment_set_id}/raptor`

Feature flags:

- `FEATURE_ENABLE_LLM`
- `FEATURE_ENABLE_GRAPH`
- `FEATURE_ENABLE_RAPTOR`
- `FEATURE_ENABLE_MINER_U`

---

For generated, always-current request/response JSON Schemas, use the runtime OpenAPI document:

- `GET /api/v1/openapi.json`
