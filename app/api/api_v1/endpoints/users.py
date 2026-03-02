from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.user_settings import UpsertUserRequest, UserOut, UserSettingsOut, UserSettingsRequest
from app.services.user_settings_service import UserSettingsService

router = APIRouter()


@router.post("/users", response_model=UserOut)
async def upsert_user(request: UpsertUserRequest, session: AsyncSession = Depends(get_session)):
    svc = UserSettingsService(session)
    row = await svc.upsert_user(request.external_subject, request.profile)
    return UserOut(
        user_id=row.user_id,
        external_subject=row.external_subject,
        profile=row.profile_json or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/users/{user_id}/settings", response_model=UserSettingsOut)
async def upsert_user_settings(user_id: str, request: UserSettingsRequest, session: AsyncSession = Depends(get_session)):
    svc = UserSettingsService(session)
    await svc.upsert_user_settings(user_id, request.settings)
    resolved = await svc.resolve_settings(user_id)
    return UserSettingsOut(user_id=user_id, settings=request.settings, resolved_settings=resolved)


@router.put("/projects/{project_id}/users/{user_id}/settings", response_model=UserSettingsOut)
async def upsert_user_project_settings(
    project_id: str,
    user_id: str,
    request: UserSettingsRequest,
    session: AsyncSession = Depends(get_session),
):
    svc = UserSettingsService(session)
    await svc.upsert_user_project_settings(user_id, project_id, request.settings)
    resolved = await svc.resolve_settings(user_id, project_id)
    return UserSettingsOut(user_id=user_id, settings=request.settings, resolved_settings=resolved)


@router.get("/users/{user_id}/settings", response_model=UserSettingsOut)
async def get_user_settings(user_id: str, project_id: str | None = None, session: AsyncSession = Depends(get_session)):
    svc = UserSettingsService(session)
    resolved = await svc.resolve_settings(user_id, project_id)
    return UserSettingsOut(user_id=user_id, settings={}, resolved_settings=resolved)

