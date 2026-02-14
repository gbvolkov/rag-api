from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Project
from app.services.project_service import ProjectService


async def require_active_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> Project:
    svc = ProjectService(session)
    return await svc.get(project_id)
