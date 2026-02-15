from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.core.capabilities import require_feature
from app.core.config import settings
from app.db.session import get_session
from app.schemas.segment import (
    ClonePatchSegmentRequest,
    CreateSegmentsRequest,
    EnrichSegmentsRequest,
    RaptorSegmentsRequest,
    SegmentSetWithItems,
)
from app.services.index_service import IndexService
from app.services.segment_service import SegmentService
from app.services.segment_transform_service import SegmentTransformService
from app.services.serializers import segment_item_out, segment_set_out
from app.workers.tasks import run_segment_enrich, run_segment_raptor

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


@router.post("/segment_sets/{segment_set_id}/enrich")
async def enrich_segment_set(
    segment_set_id: str,
    request: EnrichSegmentsRequest,
    session: AsyncSession = Depends(get_session),
):
    seg_svc = SegmentService(session)
    base = await seg_svc.get_segment_set(segment_set_id)

    if request.execution_mode == "async":
        require_feature(settings.feature_enable_llm, "llm", hint="Set FEATURE_ENABLE_LLM=true and configure provider credentials.")
        job_svc = IndexService(session)
        job = await job_svc.create_job(
            project_id=base.project_id,
            job_type="segment_enrich",
            payload={"segment_set_version_id": segment_set_id},
        )
        run_segment_enrich.delay(
            job.job_id,
            segment_set_id,
            {
                "llm_provider": request.llm_provider,
                "llm_model": request.llm_model,
                "llm_temperature": request.llm_temperature,
                "params": request.params,
            },
        )
        return {"mode": "async", "job_id": job.job_id}

    transform = SegmentTransformService(seg_svc)
    row = await transform.enrich(
        segment_set_id=segment_set_id,
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
        llm_temperature=request.llm_temperature,
        params=request.params,
    )
    items = await seg_svc.list_items(row.segment_set_version_id)
    return {
        "mode": "sync",
        "segment_set": segment_set_out(row, total_items=len(items)).model_dump(),
        "items": [segment_item_out(i).model_dump() for i in items],
    }


@router.post("/segment_sets/{segment_set_id}/raptor")
async def raptor_segment_set(
    segment_set_id: str,
    request: RaptorSegmentsRequest,
    session: AsyncSession = Depends(get_session),
):
    seg_svc = SegmentService(session)
    base = await seg_svc.get_segment_set(segment_set_id)

    if request.execution_mode == "async":
        require_feature(settings.feature_enable_raptor, "raptor", hint="Set FEATURE_ENABLE_RAPTOR=true to enable RAPTOR processing.")
        require_feature(settings.feature_enable_llm, "llm", hint="Set FEATURE_ENABLE_LLM=true and configure provider credentials.")
        job_svc = IndexService(session)
        job = await job_svc.create_job(
            project_id=base.project_id,
            job_type="segment_raptor",
            payload={"segment_set_version_id": segment_set_id},
        )
        run_segment_raptor.delay(
            job.job_id,
            segment_set_id,
            {
                "max_levels": request.max_levels,
                "llm_provider": request.llm_provider,
                "llm_model": request.llm_model,
                "llm_temperature": request.llm_temperature,
                "embedding_provider": request.embedding_provider,
                "embedding_model_name": request.embedding_model_name,
                "params": request.params,
            },
        )
        return {"mode": "async", "job_id": job.job_id}

    transform = SegmentTransformService(seg_svc)
    row = await transform.raptor(
        segment_set_id=segment_set_id,
        max_levels=request.max_levels,
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
        llm_temperature=request.llm_temperature,
        embedding_provider=request.embedding_provider,
        embedding_model_name=request.embedding_model_name,
        params=request.params,
    )
    items = await seg_svc.list_items(row.segment_set_version_id)
    return {
        "mode": "sync",
        "segment_set": segment_set_out(row, total_items=len(items)).model_dump(),
        "items": [segment_item_out(i).model_dump() for i in items],
    }
