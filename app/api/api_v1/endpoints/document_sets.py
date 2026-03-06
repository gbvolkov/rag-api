from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.core.errors import api_error
from app.db.session import get_session
from app.schemas.document_set import (
    DocumentSetWithItems,
    LoadDocumentsFromUrlRequest,
    LoadDocumentsFromUrlSubmitRequest,
    LoadDocumentsFromUrlSubmitResponse,
    LoadDocumentsRequest,
)
from app.schemas.segment import CreateSegmentsFromDocumentSetRequest, SegmentSetWithItems
from app.services.document_load_service import DocumentLoadService
from app.services.index_service import IndexService
from app.services.segment_service import SegmentService
from app.services.serializers import (
    document_item_out,
    document_set_out,
    segment_item_out,
    segment_set_out,
)

router = APIRouter()


@router.post("/document_versions/{version_id}/load_documents", response_model=DocumentSetWithItems)
async def load_documents(
    version_id: str,
    request: LoadDocumentsRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = DocumentLoadService(session)
    document_set = await svc.load_from_document_version(
        version_id=version_id,
        loader_type=request.loader_type,
        loader_params=request.loader_params,
    )
    items = await svc.list_items(document_set.document_set_version_id)
    return DocumentSetWithItems(
        document_set=document_set_out(document_set, total_items=len(items)),
        items=[document_item_out(i) for i in items],
    )


@router.post("/projects/{project_id}/load_documents/url", response_model=DocumentSetWithItems)
async def load_documents_from_url(
    project_id: str,
    request: LoadDocumentsFromUrlRequest,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = DocumentLoadService(session)
    document_set = await svc.load_from_url(
        project_id=project_id,
        loader_type=request.loader_type,
        loader_params=request.loader_params,
    )
    items = await svc.list_items(document_set.document_set_version_id)
    return DocumentSetWithItems(
        document_set=document_set_out(document_set, total_items=len(items)),
        items=[document_item_out(i) for i in items],
    )


@router.post("/projects/{project_id}/load_documents/url/submit", response_model=LoadDocumentsFromUrlSubmitResponse)
async def submit_load_documents_from_url(
    project_id: str,
    request: LoadDocumentsFromUrlSubmitRequest,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    from app.workers.tasks import run_document_load_from_url

    requested_params = dict(request.loader_params or {})
    url = str(requested_params.get("url") or "").strip()
    if not url:
        raise api_error(400, "invalid_loader_params", "loader_params.url is required for URL loading")

    svc = IndexService(session)
    job = await svc.create_job(
        project_id=project_id,
        job_type="document_load_url",
        payload={
            "project_id": project_id,
            "loader_type": request.loader_type,
            "url": url,
            "fetch_mode": requested_params.get("fetch_mode"),
        },
    )
    run_document_load_from_url.delay(job.job_id, project_id, request.loader_type, requested_params)
    return LoadDocumentsFromUrlSubmitResponse(mode="async", job_id=job.job_id, status="queued")


@router.get("/projects/{project_id}/document_sets")
async def list_document_sets(
    project_id: str,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = DocumentLoadService(session)
    rows = await svc.list_document_sets(project_id)
    result = []
    for row in rows:
        total = await svc.count_items(row.document_set_version_id)
        result.append(document_set_out(row, total_items=total))
    return result


@router.get("/document_sets/{document_set_version_id}", response_model=DocumentSetWithItems)
async def get_document_set(document_set_version_id: str, session: AsyncSession = Depends(get_session)):
    svc = DocumentLoadService(session)
    row = await svc.get_document_set(document_set_version_id)
    items = await svc.list_items(document_set_version_id)
    return DocumentSetWithItems(
        document_set=document_set_out(row, total_items=len(items)),
        items=[document_item_out(i) for i in items],
    )


@router.post("/document_sets/{document_set_version_id}/segments", response_model=SegmentSetWithItems)
async def create_segments_from_document_set(
    document_set_version_id: str,
    request: CreateSegmentsFromDocumentSetRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = SegmentService(session)
    segment_set = await svc.create_from_document_set(
        document_set_id=document_set_version_id,
        split_strategy=request.split_strategy,
        splitter_params=request.splitter_params,
        params=request.params,
    )
    items = await svc.list_items(segment_set.segment_set_version_id)
    return SegmentSetWithItems(
        segment_set=segment_set_out(segment_set, total_items=len(items)),
        items=[segment_item_out(i) for i in items],
    )
