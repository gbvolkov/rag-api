# RAG API

Project-scoped document ingestion, segmentation, chunking, indexing, retrieval, and artifact lifecycle service built on top of `rag_lib`.

## Stack

- API: FastAPI (`/api/v1`)
- DB: PostgreSQL (metadata and lineage)
- Object store: MinIO (raw files and generated artifacts)
- Vector store: Qdrant and/or FAISS (depending on index provider)
- Async runtime: Celery + Redis

## Run

### Standard Docker compose

```bash
docker compose up --build
```

- API: `http://localhost:8000`
- OpenAPI JSON: `http://localhost:8000/api/v1/openapi.json`

### If host ports are already occupied

Use an override that clears dependency host-port mappings:

```bash
docker compose -f docker-compose.yml -f docker-compose.local-noports.yml up -d --build
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

### Service Endpoints

### GET `/`

Returns service identity.

Response `200`:

```json
{
  "service": "RAG API",
  "api": "/api/v1"
}
```

### GET `/health`

Liveness endpoint.

Response `200`:

```json
{
  "status": "ok"
}
```

## Projects

### POST `/api/v1/projects`

Creates a project.

Request body (`CreateProjectRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | yes | - | 1..200 chars |
| `description` | string \| null | no | `null` | max 2000 chars |
| `settings` | object | no | `{}` | `ProjectSettings` |
| `settings.default_retrieval_preset` | string \| null | no | `null` | optional preset label |
| `settings.default_chunking_preset` | string \| null | no | `null` | optional preset label |
| `settings.extra` | object | no | `{}` | arbitrary JSON |

Response `200`: `ProjectOut`

### GET `/api/v1/projects`

Lists projects ordered by newest first.

Response `200`: `ProjectOut[]`

### GET `/api/v1/projects/{project_id}`

Gets one project.

Path params:

| Name | Type | Required | Notes |
|---|---|---|---|
| `project_id` | string | yes | project identifier |

Response `200`: `ProjectOut`

### PATCH `/api/v1/projects/{project_id}`

Partially updates project fields.

Path params:

| Name | Type | Required | Notes |
|---|---|---|---|
| `project_id` | string | yes | project identifier |

Request body (`UpdateProjectRequest`, all optional):

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string \| null | no | 1..200 chars if supplied |
| `description` | string \| null | no | max 2000 chars |
| `settings` | object \| null | no | full `ProjectSettings` replacement |

Response `200`: `ProjectOut`

## Documents

### POST `/api/v1/projects/{project_id}/documents`

Uploads one raw file and creates:

1. `Document`
2. active `DocumentVersion`

Path params:

| Name | Type | Required | Notes |
|---|---|---|---|
| `project_id` | string | yes | project identifier |

Multipart form fields:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `file` | binary file | yes | - | uploaded content |
| `parser_params_json` | string \| null | no | `null` | JSON string; parsed with `json.loads` |

Response `200`:

```json
{
  "document": { "...DocumentOut fields..." },
  "document_version": { "...DocumentVersionOut fields..." }
}
```

### GET `/api/v1/projects/{project_id}/documents`

Lists non-deleted documents in project, newest first.

Path params:

| Name | Type | Required | Notes |
|---|---|---|---|
| `project_id` | string | yes | project identifier |

Response `200`: `DocumentOut[]`

### GET `/api/v1/documents/{document_id}`

Gets one non-deleted document.

Path params:

| Name | Type | Required |
|---|---|---|
| `document_id` | string | yes |

Response `200`: `DocumentOut`

### GET `/api/v1/documents/{document_id}/versions`

Lists non-deleted versions for document, newest first.

Path params:

| Name | Type | Required |
|---|---|---|
| `document_id` | string | yes |

Response `200`: `DocumentVersionOut[]`

## Segments

### POST `/api/v1/document_versions/{version_id}/segments`

Builds a new `SegmentSetVersion` and segment items from a document version.

Path params:

| Name | Type | Required |
|---|---|---|
| `version_id` | string | yes |

Request body (`CreateSegmentsRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `loader_type` | string | yes | - | `pdf`, `docx`, `csv`, `excel`, `json`, `qa`, `table` |
| `loader_params` | object | no | `{}` | loader-specific options |
| `source_text` | string \| null | no | `null` | if provided, loader is bypassed and a single text segment is produced |

Response `200`: `SegmentSetWithItems`

### GET `/api/v1/projects/{project_id}/segment_sets`

Lists non-deleted segment sets for project, newest first.

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Response `200`: `SegmentSetOut[]`

### GET `/api/v1/segment_sets/{segment_set_id}`

Gets one segment set with all items.

Path params:

| Name | Type | Required |
|---|---|---|
| `segment_set_id` | string | yes |

Response `200`: `SegmentSetWithItems`

### POST `/api/v1/segment_sets/{segment_set_id}/clone_patch_item`

Creates a new derived segment set version by cloning all items and patching one item.

Path params:

| Name | Type | Required |
|---|---|---|
| `segment_set_id` | string | yes |

Request body (`ClonePatchSegmentRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `item_id` | string | yes | item to patch |
| `patch` | object | yes | supported keys: `content`, `metadata`, `parent_id`, `level`, `path`, `type`, `original_format` |
| `params` | object | no | free-form metadata persisted under `segment_set.params.clone_patch` |

Response `200`: `SegmentSetWithItems`

## Chunks

### POST `/api/v1/segment_sets/{segment_set_id}/chunk`

Builds a new `ChunkSetVersion` from one segment set.

Path params:

| Name | Type | Required |
|---|---|---|
| `segment_set_id` | string | yes |

Request body (`ChunkFromSegmentRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `strategy` | string | no | `recursive` | see chunk strategy matrix below |
| `chunker_params` | object | no | `{}` | strategy-specific options |

Response `200`: `ChunkSetWithItems`

### GET `/api/v1/projects/{project_id}/chunk_sets`

Lists non-deleted chunk sets for project, newest first.

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Response `200`: `ChunkSetOut[]`

### GET `/api/v1/chunk_sets/{chunk_set_id}`

Gets one chunk set with all chunk items.

Path params:

| Name | Type | Required |
|---|---|---|
| `chunk_set_id` | string | yes |

Response `200`: `ChunkSetWithItems`

### POST `/api/v1/chunk_sets/{chunk_set_id}/clone_patch_item`

Creates a new derived chunk set by cloning all items and patching one item.

Path params:

| Name | Type | Required |
|---|---|---|
| `chunk_set_id` | string | yes |

Request body (`ClonePatchChunkRequest`):

| Field | Type | Required | Notes |
|---|---|---|---|
| `item_id` | string | yes | chunk item id to patch |
| `patch` | object | yes | supported keys: `content`, `metadata`, `parent_id`, `level`, `path`, `type`, `original_format` |
| `params` | object | no | free-form metadata persisted under `chunk_set.params.clone_patch` |

Response `200`: `ChunkSetWithItems`

## Indexes

### POST `/api/v1/projects/{project_id}/indexes`

Creates index metadata row (does not build vectors yet).

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Request body (`CreateIndexRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | yes | - | display name |
| `provider` | string | no | `qdrant` | implemented: `qdrant`, `faiss` |
| `index_type` | string | no | `chunk_vectors` | currently treated as metadata |
| `config` | object | no | `{}` | provider/build config |
| `params` | object | no | `{}` | user metadata |

Response `200`: `IndexOut`

### GET `/api/v1/projects/{project_id}/indexes`

Lists non-deleted indexes for project.

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Response `200`: `IndexOut[]`

### GET `/api/v1/indexes/{index_id}`

Gets one index.

Path params:

| Name | Type | Required |
|---|---|---|
| `index_id` | string | yes |

Response `200`: `IndexOut`

### POST `/api/v1/indexes/{index_id}/builds`

Creates and optionally executes an index build.

Path params:

| Name | Type | Required |
|---|---|---|
| `index_id` | string | yes |

Request body (`CreateIndexBuildRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `chunk_set_version_id` | string | yes | - | source chunks |
| `params` | object | no | `{}` | build metadata (persisted) |
| `execution_mode` | string | no | `sync` | `async` queues Celery job; any non-`async` value runs sync |

Response `200` (sync):

```json
{
  "mode": "sync",
  "build": { "...IndexBuildOut..." }
}
```

Response `200` (async):

```json
{
  "mode": "async",
  "job_id": "string",
  "build": { "...IndexBuildOut..." }
}
```

### GET `/api/v1/indexes/{index_id}/builds`

Lists non-deleted builds for index.

Path params:

| Name | Type | Required |
|---|---|---|
| `index_id` | string | yes |

Response `200`: `IndexBuildOut[]`

### GET `/api/v1/index_builds/{build_id}`

Gets one build.

Path params:

| Name | Type | Required |
|---|---|---|
| `build_id` | string | yes |

Response `200`: `IndexBuildOut`

## Retrieval

### POST `/api/v1/projects/{project_id}/retrieve`

Runs retrieval over chunk sets, segment sets, or vector index builds.

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Request body (`RetrieveRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `query` | string | yes | - | user query |
| `target` | string | no | `chunk_set` | `chunk_set`, `segment_set`, `index_build` |
| `target_id` | string \| null | no | `null` | optional for chunk/segment targets, required for vector/dual strategies |
| `strategy` | object | yes | - | discriminated union by `type` |
| `persist` | boolean | no | `false` | if true, stores retrieval run + artifact |
| `limit` | integer | no | `20` | page size (clamped to `1..200`) |
| `cursor` | string \| null | no | `null` | Base64 offset cursor |

Response `200`: `RetrieveResponse`

### GET `/api/v1/projects/{project_id}/retrieval_runs`

Lists non-deleted persisted retrieval runs for a project.

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Response `200`: `RetrievalRunOut[]`

### GET `/api/v1/retrieval_runs/{run_id}`

Gets one persisted retrieval run.

Path params:

| Name | Type | Required |
|---|---|---|
| `run_id` | string | yes |

Response `200`: `RetrievalRunOut`

### DELETE `/api/v1/retrieval_runs/{run_id}`

Soft-deletes retrieval run row.

Path params:

| Name | Type | Required |
|---|---|---|
| `run_id` | string | yes |

Response `200`:

```json
{
  "ok": true,
  "run_id": "string"
}
```

## Jobs

### GET `/api/v1/projects/{project_id}/jobs`

Lists jobs for one project.

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Response `200`: `JobOut[]`

### GET `/api/v1/jobs/{job_id}`

Gets one job.

Path params:

| Name | Type | Required |
|---|---|---|
| `job_id` | string | yes |

Response `200`: `JobOut`

### GET `/api/v1/admin/jobs`

Lists all jobs across projects.

Response `200`: `JobOut[]`

## Pipeline

### POST `/api/v1/projects/{project_id}/pipeline/file`

One-shot pipeline endpoint: upload -> segments -> chunks -> optional index build.

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Multipart form fields:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `file` | binary file | yes | - | source file |
| `loader_type` | string | yes | - | segment loader type |
| `loader_params_json` | string \| null | no | `null` | JSON string for loader params |
| `chunk_strategy` | string | no | `recursive` | chunk strategy |
| `chunker_params_json` | string \| null | no | `null` | JSON string for chunk params |
| `create_index` | boolean | no | `false` | enable build attempt |
| `index_id` | string \| null | no | `null` | existing index id to build against |
| `index_params_json` | string \| null | no | `null` | JSON string for build params |
| `execution_mode` | string | no | `sync` | `async` queues job; any non-`async` behaves as sync |

Behavior notes:

- If `execution_mode == "async"`:
  - returns immediately with `status="queued"` and `job_id`
  - `document_id`, `document_version_id`, `segment_set_version_id`, `chunk_set_version_id` are empty strings in the immediate response
- If sync:
  - returns actual generated IDs with `status="succeeded"`
- Index build occurs only when `create_index == true` and `index_id` is provided.

Response `200`: `PipelineResponse`

## Artifacts

### GET `/api/v1/projects/{project_id}/artifacts`

Unified artifact feed for a project (documents, versions, segment sets, chunk sets, indexes, builds, retrieval runs).

Path params:

| Name | Type | Required |
|---|---|---|
| `project_id` | string | yes |

Query params:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `limit` | integer | no | settings default (20) | min 1, max 200 |
| `cursor` | string \| null | no | `null` | Base64 offset cursor |

Response `200`:

```json
{
  "items": [{ "...ArtifactOut..." }],
  "next_cursor": "string-or-null",
  "has_more": true,
  "total": 123
}
```

### DELETE `/api/v1/artifacts/{artifact_id}`

Soft-deletes one artifact row.

Path params:

| Name | Type | Required |
|---|---|---|
| `artifact_id` | string | yes |

Request body (`SoftDeleteRequest`):

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `reason` | string \| null | no | `null` | audit reason |

Response `200`: `DeleteResponse`

### POST `/api/v1/artifacts/{artifact_id}/restore`

Restores previously soft-deleted artifact.

Path params:

| Name | Type | Required |
|---|---|---|
| `artifact_id` | string | yes |

Response `200`: `RestoreResponse`

## Segment and Chunk Details (Strategies, Types, Options)

## Segment loader types

Used by `POST /api/v1/document_versions/{version_id}/segments` when `source_text` is absent.

| Loader `loader_type` | Supported params (`loader_params`) | Notes |
|---|---|---|
| `pdf` | `backend` | Delegates to `rag_lib.loaders.pdf.PDFLoader` |
| `docx` | `regex_patterns`, `exclude_patterns`, `include_parent_content` (default `true`) | Structured loader |
| `csv` | `chunk_size` | CSV loader |
| `excel` | none | Excel loader |
| `json` | `jq_schema` (default `"."`) | JSON loader |
| `qa` | none | QA loader |
| `table` | `mode` (default `"row"`), `group_by` | table rows/groups |

Important behavior:

- If `source_text` is provided, service returns exactly one text segment and ignores file loader execution.
- Unsupported loader without `source_text` returns `400 unsupported_loader`.

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

## Versioning/active semantics for segments and chunks

- New segment set creation deactivates active sets for the same `document_version_id`.
- Segment clone-patch creates a child set with `parent_segment_set_version_id` and deactivates prior active set for same doc version.
- New chunk set creation deactivates active chunk sets for the project.
- Chunk clone-patch creates a child set with `parent_chunk_set_version_id` and deactivates prior active project chunk sets.

## Indexes (Strategies, Providers, Types, Options)

## Index providers

| Provider | Build behavior | Retrieval behavior |
|---|---|---|
| `qdrant` | Embeds chunks, creates/upserts Qdrant collection | Vector and dual-storage retrieval supported |
| `faiss` | Builds local FAISS index in `artifacts/faiss/<project>/<index>/<build>` | Vector retrieval via local FAISS load |

Any other provider returns `501 provider_unsupported` for build/retrieval execution.

## `index_type`

Default is `chunk_vectors`. It is persisted as metadata; current build logic does not branch on this field.

## Index config options used by implementation

| Config field | Scope | Default | Notes |
|---|---|---|---|
| `embedding_provider` | qdrant/faiss build + vector retrieval | `mock` | `mock` uses deterministic mock embeddings |
| `embedding_model_name` | qdrant/faiss | `null` | forwarded to embedding factory when provider != `mock` |
| `collection_name` | qdrant | generated `rag_api_<project_id>_<index_id>` | custom Qdrant collection name |
| `faiss_local_dir` | faiss | generated during build | populated after successful FAISS build |

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
| `search_type` | string | `similarity` | accepted but currently not applied in backend query |
| `score_threshold` | float \| null | `null` | accepted but currently not applied |

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

If `sources` is empty, service uses default ensemble composition (BM25 when available + regex + fuzzy).

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
| `id_key` | string | `segment_id` | currently accepted but not used by implementation |

Constraints:

- Requires `target="index_build"` and non-null `target_id`.
- Currently supports only qdrant-backed index builds.

## Retrieval target semantics

| Target | `target_id` required? | Data source |
|---|---|---|
| `chunk_set` | no (optional) | chunk items (if missing, latest active chunk set is used) |
| `segment_set` | no (optional) | segment items (if missing, latest active segment set is used) |
| `index_build` | yes for vector/dual | vector index build + provider-specific backend |

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
| `segment_set_version_id` | string |
| `chunk_set_version_id` | string |
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

---

For generated, always-current request/response JSON Schemas, use the runtime OpenAPI document:

- `GET /api/v1/openapi.json`
