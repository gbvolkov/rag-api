from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.job import JobOut
from app.services.job_service import JobService
from app.services.serializers import job_out

router = APIRouter(prefix="/admin")


@router.get("/jobs", response_model=list[JobOut])
async def list_all_jobs(session: AsyncSession = Depends(get_session)):
    svc = JobService(session)
    rows = await svc.list_all()
    return [job_out(r) for r in rows]
