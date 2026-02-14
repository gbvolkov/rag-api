from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.core.config import settings
from app.core.pagination import encode_cursor, paginate
from app.db.session import get_session
from app.schemas.artifact import ArtifactOut
from app.schemas.common import DeleteResponse, RestoreResponse, SoftDeleteRequest
from app.services.artifact_service import ArtifactService

router = APIRouter()


@router.get("/projects/{project_id}/artifacts")
async def list_artifacts(
    project_id: str,
    limit: int = Query(default=settings.page_size_default, ge=1),
    cursor: str | None = Query(default=None),
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = ArtifactService(session)
    rows = await svc.list_project_artifacts(project_id)
    page = paginate(limit, cursor, settings.page_size_default, settings.page_size_max)
    total = len(rows)
    sliced = rows[page.offset : page.offset + page.limit]
    next_offset = page.offset + page.limit if page.offset + page.limit < total else None

    return {
        "items": [ArtifactOut(**r).model_dump() for r in sliced],
        "next_cursor": encode_cursor(next_offset),
        "has_more": next_offset is not None,
        "total": total,
    }


@router.delete("/artifacts/{artifact_id}", response_model=DeleteResponse)
async def soft_delete_artifact(
    artifact_id: str,
    request: SoftDeleteRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = ArtifactService(session)
    payload = await svc.soft_delete(artifact_id, request.reason)
    return DeleteResponse(ok=True, **payload)


@router.post("/artifacts/{artifact_id}/restore", response_model=RestoreResponse)
async def restore_artifact(artifact_id: str, session: AsyncSession = Depends(get_session)):
    svc = ArtifactService(session)
    payload = await svc.restore(artifact_id)
    return RestoreResponse(ok=True, **payload)
