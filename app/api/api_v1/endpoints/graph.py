from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.db.session import get_session
from app.schemas.graph import CreateGraphBuildRequest, GraphBuildOut
from app.services.graph_service import GraphService
from app.services.index_service import IndexService
from app.services.serializers import graph_build_out
from app.workers.tasks import run_graph_build

router = APIRouter()


@router.post("/projects/{project_id}/graph/builds")
async def create_graph_build(
    project_id: str,
    request: CreateGraphBuildRequest,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = GraphService(session)
    build = await svc.create_build(
        project_id=project_id,
        source_type=request.source_type,
        source_id=request.source_id,
        backend=request.backend,
        params={
            "extract_entities": request.extract_entities,
            "detect_communities": request.detect_communities,
            "summarize_communities": request.summarize_communities,
            "llm_provider": request.llm_provider,
            "llm_model": request.llm_model,
            "llm_temperature": request.llm_temperature,
            "search_depth": request.search_depth,
            **request.params,
        },
        status="queued",
    )

    if request.execution_mode == "async":
        job_svc = IndexService(session)
        job = await job_svc.create_job(
            project_id=project_id,
            job_type="graph_build",
            payload={"graph_build_id": build.graph_build_id, "source_type": request.source_type, "source_id": request.source_id},
        )
        run_graph_build.delay(job.job_id, build.graph_build_id)
        return {"mode": "async", "job_id": job.job_id, "build": graph_build_out(build).model_dump()}

    final = await svc.run_build(build.graph_build_id)
    return {"mode": "sync", "build": graph_build_out(final).model_dump()}


@router.get("/projects/{project_id}/graph/builds", response_model=list[GraphBuildOut])
async def list_graph_builds(
    project_id: str,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = GraphService(session)
    rows = await svc.list_builds(project_id)
    return [graph_build_out(r) for r in rows]


@router.get("/graph_builds/{graph_build_id}", response_model=GraphBuildOut)
async def get_graph_build(graph_build_id: str, session: AsyncSession = Depends(get_session)):
    svc = GraphService(session)
    row = await svc.get_build(graph_build_id)
    return graph_build_out(row)

