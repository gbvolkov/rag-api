# Test Report

## Run Metadata
- Date: 2026-02-14 00:48:10 +03:00
- Workspace: `c:\Projects\kbman_svc`
- Command: `pytest -vv -p no:cacheprovider`
- Python: `3.13.7`
- Pytest: `8.3.3`

## Scope Executed
- `tests/integration/test_comprehensive_api_matrix.py` (20)
- `tests/integration/test_index_api.py` (1)
- `tests/integration/test_lifecycle_api.py` (2)
- `tests/integration/test_pipeline_e2e.py` (4)
- `tests/integration/test_retrieval_strategy_matrix.py` (16)
- `tests/unit/test_pagination.py` (2)

Collected tests: **45**

## Results
- Passed: **45**
- Failed: **0**
- Errors: **0**
- Skipped: **0**
- Total duration: **13.76s**

## Coverage Highlights
- Retriever strategy matrix covered:
  - atomic: `vector`, `bm25`, `regex`, `fuzzy`
  - composed: `ensemble` (explicit and default sources), `rerank` (regex-base and vector-base), `dual_storage`
  - targets: `chunk_set`, `segment_set`, `index_build`
  - retrieval pagination and cursor contract
- Artifact/versioning lifecycle covered:
  - project/document/version CRUD/list endpoints
  - segment/chunk creation across loader/chunker strategy matrices
  - immutable clone-patch for segment/chunk with parent linkage + active pointer movement
  - unified artifact listing with cursor pagination
  - soft-delete + restore matrix for `document`, `document_version`, `segment_set`, `chunk_set`, `index`, `index_build`, `retrieval_run`
- Parameter persistence covered:
  - document parser params
  - segment/chunk generation params and lineage refs
  - index and index-build params
  - persisted retrieval run params payload
- End-to-end pipeline coverage:
  - sync pipeline: ingest -> segment -> chunk -> FAISS build -> vector retrieve
  - sync pipeline: ingest -> segment -> chunk (no index) -> unindexed retrieve
  - async pipeline job flow with project/admin job visibility and retrieval from produced chunk set
  - async index-build job flow with build listing/get and post-build vector retrieval

## Warnings Observed (10)
1. FastAPI deprecation (`@app.on_event("startup")`): migrate to lifespan handlers.
2. Pydantic v2 deprecation warning for class-based config in upstream dependencies.
3. SWIG deprecation warnings from FAISS-related runtime types (`SwigPyPacked`, `SwigPyObject`, `swigvarlink`).

## Notes
- During expansion, two defects were detected and fixed, then validated by the full passing run:
  - local FS object-store URI key normalization in `app/storage/keys.py` (prevented duplicated root path resolution)
  - retrieval preloading logic in `app/services/retrieval_service.py` for `dual_storage` and `rerank(base=vector)` paths

## Conclusion
The expanded comprehensive suite passed fully (`45/45`). Strategy matrix coverage, artifact lifecycle semantics, parameter persistence, and full pipeline E2E flows are all validated in the current implementation.
