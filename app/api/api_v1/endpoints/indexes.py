from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.db.session import get_session
from app.schemas.indexing import CreateIndexBuildRequest, CreateIndexRequest, IndexBuildOut, IndexOut
from app.services.index_service import IndexService
from app.services.serializers import index_build_out, index_out
from app.workers.tasks import run_index_build

router = APIRouter()


@router.post("/projects/{project_id}/indexes", response_model=IndexOut)
async def create_index(
    project_id: str,
    request: CreateIndexRequest,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = IndexService(session)
    row = await svc.create_index(
        project_id=project_id,
        name=request.name,
        provider=request.provider,
        index_type=request.index_type,
        config=request.config,
        params=request.params,
    )
    return index_out(row)


@router.get("/projects/{project_id}/indexes", response_model=list[IndexOut])
async def list_indexes(
    project_id: str,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = IndexService(session)
    rows = await svc.list_indexes(project_id)
    return [index_out(r) for r in rows]


@router.get("/indexes/{index_id}", response_model=IndexOut)
async def get_index(index_id: str, session: AsyncSession = Depends(get_session)):
    svc = IndexService(session)
    row = await svc.get_index(index_id)
    return index_out(row)


@router.post("/indexes/{index_id}/builds")
async def create_index_build(index_id: str, request: CreateIndexBuildRequest, session: AsyncSession = Depends(get_session)):
    svc = IndexService(session)
    build = await svc.create_build(index_id, request.chunk_set_version_id, request.params, status="queued")

    if request.execution_mode == "async":
        job = await svc.create_job(build.project_id, "index_build", {"build_id": build.build_id, "index_id": build.index_id})
        run_index_build.delay(job.job_id, build.build_id)
        return {"mode": "async", "job_id": job.job_id, "build": index_build_out(build).model_dump()}

    final_build = await svc.run_build(build.build_id)
    return {"mode": "sync", "build": index_build_out(final_build).model_dump()}


@router.get("/indexes/{index_id}/builds", response_model=list[IndexBuildOut])
async def list_index_builds(index_id: str, session: AsyncSession = Depends(get_session)):
    svc = IndexService(session)
    rows = await svc.list_builds(index_id)
    return [index_build_out(r) for r in rows]


@router.get("/index_builds/{build_id}", response_model=IndexBuildOut)
async def get_index_build(build_id: str, session: AsyncSession = Depends(get_session)):
    svc = IndexService(session)
    row = await svc.get_build(build_id)
    return index_build_out(row)
