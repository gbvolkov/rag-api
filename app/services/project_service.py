from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import api_error
from app.models import Project
from app.schemas.project import CreateProjectRequest, UpdateProjectRequest


class ProjectService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, request: CreateProjectRequest) -> Project:
        row = Project(name=request.name, description=request.description, settings_json=request.settings.model_dump())
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list(self) -> list[Project]:
        stmt = select(Project).where(Project.is_deleted.is_(False)).order_by(Project.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, project_id: str) -> Project:
        row = await self.session.get(Project, project_id)
        if not row or row.is_deleted:
            raise api_error(404, "project_not_found", "Project not found", {"project_id": project_id})
        return row

    async def update(self, project_id: str, request: UpdateProjectRequest) -> Project:
        row = await self.get(project_id)
        if request.name is not None:
            row.name = request.name
        if request.description is not None:
            row.description = request.description
        if request.settings is not None:
            row.settings_json = request.settings.model_dump()
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def soft_delete(self, project_id: str) -> Project:
        row = await self.get(project_id)
        row.is_deleted = True
        await self.session.commit()
        await self.session.refresh(row)
        return row
