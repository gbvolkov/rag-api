from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.db.session import get_session
from app.schemas.chunk import ChunkFromSegmentRequest, ChunkSetWithItems, ClonePatchChunkRequest
from app.services.chunk_service import ChunkService
from app.services.serializers import chunk_item_out, chunk_set_out

router = APIRouter()


@router.post("/segment_sets/{segment_set_id}/chunk", response_model=ChunkSetWithItems)
async def chunk_segment_set(
    segment_set_id: str,
    request: ChunkFromSegmentRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = ChunkService(session)
    row = await svc.create_from_segment_set(segment_set_id, request.strategy, request.chunker_params)
    items = await svc.list_items(row.chunk_set_version_id)
    return ChunkSetWithItems(
        chunk_set=chunk_set_out(row, total_items=len(items)),
        items=[chunk_item_out(i) for i in items],
    )


@router.get("/projects/{project_id}/chunk_sets")
async def list_chunk_sets(
    project_id: str,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = ChunkService(session)
    rows = await svc.list_chunk_sets(project_id)
    result = []
    for row in rows:
        count = await svc.count_items(row.chunk_set_version_id)
        result.append(chunk_set_out(row, total_items=count))
    return result


@router.get("/chunk_sets/{chunk_set_id}", response_model=ChunkSetWithItems)
async def get_chunk_set(chunk_set_id: str, session: AsyncSession = Depends(get_session)):
    svc = ChunkService(session)
    row = await svc.get_chunk_set(chunk_set_id)
    items = await svc.list_items(chunk_set_id)
    return ChunkSetWithItems(
        chunk_set=chunk_set_out(row, total_items=len(items)),
        items=[chunk_item_out(i) for i in items],
    )


@router.post("/chunk_sets/{chunk_set_id}/clone_patch_item", response_model=ChunkSetWithItems)
async def clone_patch_chunk_item(
    chunk_set_id: str,
    request: ClonePatchChunkRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = ChunkService(session)
    row = await svc.clone_patch_item(chunk_set_id, request.item_id, request.patch, request.params)
    items = await svc.list_items(row.chunk_set_version_id)
    return ChunkSetWithItems(
        chunk_set=chunk_set_out(row, total_items=len(items)),
        items=[chunk_item_out(i) for i in items],
    )
