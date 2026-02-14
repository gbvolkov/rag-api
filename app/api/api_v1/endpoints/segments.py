from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.db.session import get_session
from app.schemas.segment import (
    ClonePatchSegmentRequest,
    CreateSegmentsRequest,
    SegmentSetWithItems,
)
from app.services.segment_service import SegmentService
from app.services.serializers import segment_item_out, segment_set_out

router = APIRouter()


@router.post("/document_versions/{version_id}/segments", response_model=SegmentSetWithItems)
async def create_segments(version_id: str, request: CreateSegmentsRequest, session: AsyncSession = Depends(get_session)):
    svc = SegmentService(session)
    segment_set = await svc.create_from_document_version(
        version_id=version_id,
        loader_type=request.loader_type,
        loader_params=request.loader_params,
        source_text=request.source_text,
    )
    items = await svc.list_items(segment_set.segment_set_version_id)
    total = len(items)
    return SegmentSetWithItems(
        segment_set=segment_set_out(segment_set, total_items=total),
        items=[segment_item_out(i) for i in items],
    )


@router.get("/projects/{project_id}/segment_sets")
async def list_segment_sets(
    project_id: str,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = SegmentService(session)
    rows = await svc.list_segment_sets(project_id)
    result = []
    for row in rows:
        total = await svc.count_items(row.segment_set_version_id)
        result.append(segment_set_out(row, total_items=total))
    return result


@router.get("/segment_sets/{segment_set_id}", response_model=SegmentSetWithItems)
async def get_segment_set(segment_set_id: str, session: AsyncSession = Depends(get_session)):
    svc = SegmentService(session)
    row = await svc.get_segment_set(segment_set_id)
    items = await svc.list_items(segment_set_id)
    return SegmentSetWithItems(
        segment_set=segment_set_out(row, total_items=len(items)),
        items=[segment_item_out(i) for i in items],
    )


@router.post("/segment_sets/{segment_set_id}/clone_patch_item", response_model=SegmentSetWithItems)
async def clone_patch_segment_item(
    segment_set_id: str,
    request: ClonePatchSegmentRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = SegmentService(session)
    row = await svc.clone_patch_item(segment_set_id, request.item_id, request.patch, request.params)
    items = await svc.list_items(row.segment_set_version_id)
    return SegmentSetWithItems(
        segment_set=segment_set_out(row, total_items=len(items)),
        items=[segment_item_out(i) for i in items],
    )
