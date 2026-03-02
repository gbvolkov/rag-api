from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import api_error
from app.models import Project, User, UserProjectSettings, UserSettings


class UserSettingsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_user(self, external_subject: str, profile: dict) -> User:
        stmt = select(User).where(User.external_subject == external_subject, User.is_deleted.is_(False))
        existing = (await self.session.execute(stmt)).scalars().first()
        if existing:
            existing.profile_json = profile
            await self.session.commit()
            await self.session.refresh(existing)
            return existing
        row = User(external_subject=external_subject, profile_json=profile)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def get_user(self, user_id: str) -> User:
        row = await self.session.get(User, user_id)
        if not row or row.is_deleted:
            raise api_error(404, "user_not_found", "User not found", {"user_id": user_id})
        return row

    async def upsert_user_settings(self, user_id: str, settings: dict) -> UserSettings:
        await self.get_user(user_id)
        stmt = select(UserSettings).where(UserSettings.user_id == user_id)
        row = (await self.session.execute(stmt)).scalars().first()
        if row:
            row.settings_json = settings
        else:
            row = UserSettings(user_id=user_id, settings_json=settings)
            self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def upsert_user_project_settings(self, user_id: str, project_id: str, settings: dict) -> UserProjectSettings:
        await self.get_user(user_id)
        project = await self.session.get(Project, project_id)
        if not project or project.is_deleted:
            raise api_error(404, "project_not_found", "Project not found", {"project_id": project_id})
        stmt = select(UserProjectSettings).where(
            UserProjectSettings.user_id == user_id,
            UserProjectSettings.project_id == project_id,
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row:
            row.settings_json = settings
        else:
            row = UserProjectSettings(user_id=user_id, project_id=project_id, settings_json=settings)
            self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def resolve_settings(self, user_id: str, project_id: str | None = None) -> dict:
        user = await self.get_user(user_id)
        stmt = select(UserSettings).where(UserSettings.user_id == user.user_id)
        global_settings = (await self.session.execute(stmt)).scalars().first()
        resolved = dict(global_settings.settings_json if global_settings else {})
        if project_id:
            project_stmt = select(UserProjectSettings).where(
                UserProjectSettings.user_id == user.user_id,
                UserProjectSettings.project_id == project_id,
            )
            project_settings = (await self.session.execute(project_stmt)).scalars().first()
            if project_settings:
                resolved.update(project_settings.settings_json or {})
        return resolved

