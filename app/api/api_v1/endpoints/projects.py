from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.project import CreateProjectRequest, ProjectDeleteResponse, ProjectOut, UpdateProjectRequest
from app.services.project_service import ProjectService
from app.services.serializers import project_out

router = APIRouter(prefix="/projects")


@router.post("", response_model=ProjectOut)
async def create_project(request: CreateProjectRequest, session: AsyncSession = Depends(get_session)):
    svc = ProjectService(session)
    row = await svc.create(request)
    return project_out(row)


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)):
    svc = ProjectService(session)
    rows = await svc.list()
    return [project_out(r) for r in rows]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, session: AsyncSession = Depends(get_session)):
    svc = ProjectService(session)
    row = await svc.get(project_id)
    return project_out(row)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, request: UpdateProjectRequest, session: AsyncSession = Depends(get_session)):
    svc = ProjectService(session)
    row = await svc.update(project_id, request)
    return project_out(row)


@router.delete("/{project_id}", response_model=ProjectDeleteResponse)
async def delete_project(project_id: str, session: AsyncSession = Depends(get_session)):
    svc = ProjectService(session)
    row = await svc.soft_delete(project_id)
    return ProjectDeleteResponse(ok=True, project_id=row.project_id)
