from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import api_error
from app.models import Job


class JobService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, job_id: str) -> Job:
        row = await self.session.get(Job, job_id)
        if not row:
            raise api_error(404, "job_not_found", "Job not found", {"job_id": job_id})
        return row

    async def list_project(self, project_id: str) -> list[Job]:
        stmt = select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self) -> list[Job]:
        stmt = select(Job).order_by(Job.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(self, job_id: str, status: str, result_json: dict | None = None, error_message: str | None = None) -> Job:
        row = await self.get(job_id)
        row.status = status
        if result_json is not None:
            row.result_json = result_json
        row.error_message = error_message
        await self.session.commit()
        await self.session.refresh(row)
        return row
