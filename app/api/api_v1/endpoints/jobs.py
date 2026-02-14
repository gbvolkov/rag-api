from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.db.session import get_session
from app.schemas.job import JobOut
from app.services.job_service import JobService
from app.services.serializers import job_out

router = APIRouter()


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
async def list_project_jobs(
    project_id: str,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = JobService(session)
    rows = await svc.list_project(project_id)
    return [job_out(r) for r in rows]


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    svc = JobService(session)
    row = await svc.get(job_id)
    return job_out(row)
