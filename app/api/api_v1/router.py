from fastapi import APIRouter

from app.api.api_v1.endpoints import (
    admin,
    artifacts,
    chunks,
    documents,
    indexes,
    jobs,
    pipeline,
    projects,
    retrieval,
    segments,
)

api_router = APIRouter()
api_router.include_router(projects.router, tags=["projects"])
api_router.include_router(documents.router, tags=["documents"])
api_router.include_router(segments.router, tags=["segments"])
api_router.include_router(chunks.router, tags=["chunks"])
api_router.include_router(indexes.router, tags=["indexes"])
api_router.include_router(retrieval.router, tags=["retrieval"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(pipeline.router, tags=["pipeline"])
api_router.include_router(artifacts.router, tags=["artifacts"])
