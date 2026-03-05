from sqlalchemy import inspect, text

from app.db.session import engine
from app.models import Base


def _ensure_projects_is_deleted_column(sync_conn) -> None:
    inspector = inspect(sync_conn)
    project_columns = {col["name"] for col in inspector.get_columns("projects")}
    if "is_deleted" in project_columns:
        return
    sync_conn.execute(text("ALTER TABLE projects ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE"))


def _ensure_index_builds_segment_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    if "index_builds" not in set(inspector.get_table_names()):
        return

    index_build_columns = {col["name"] for col in inspector.get_columns("index_builds")}
    if "source_set_id" not in index_build_columns:
        sync_conn.execute(text("ALTER TABLE index_builds ADD COLUMN source_set_id VARCHAR(64)"))
        if "chunk_set_version_id" in index_build_columns:
            sync_conn.execute(text("UPDATE index_builds SET source_set_id = chunk_set_version_id WHERE source_set_id IS NULL"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_index_builds_source_set_id ON index_builds (source_set_id)"))

    if "parent_set_id" not in index_build_columns:
        sync_conn.execute(text("ALTER TABLE index_builds ADD COLUMN parent_set_id VARCHAR(64)"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_index_builds_parent_set_id ON index_builds (parent_set_id)"))

    # Legacy schema used chunk_set_version_id as required. Keep it for backward compatibility,
    # but make it optional so new inserts that use source_set_id don't fail.
    if "chunk_set_version_id" in index_build_columns:
        sync_conn.execute(text("ALTER TABLE index_builds ALTER COLUMN chunk_set_version_id DROP NOT NULL"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_projects_is_deleted_column)
        await conn.run_sync(_ensure_index_builds_segment_columns)
