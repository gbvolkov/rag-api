from sqlalchemy import inspect, text

from app.db.session import engine
from app.models import Base


def _ensure_projects_is_deleted_column(sync_conn) -> None:
    inspector = inspect(sync_conn)
    project_columns = {col["name"] for col in inspector.get_columns("projects")}
    if "is_deleted" in project_columns:
        return
    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_projects_is_deleted_column)
