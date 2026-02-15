from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import api_error
from app.models import (
    ArtifactSoftDelete,
    ChunkSetVersion,
    Document,
    DocumentVersion,
    GraphBuild,
    Index,
    IndexBuild,
    RetrievalRun,
    SegmentSetVersion,
)


class ArtifactService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_project_artifacts(self, project_id: str) -> list[dict]:
        items: list[dict] = []

        async def add_rows(stmt, kind: str, id_field: str, created_field: str, deleted_field: str, meta_fn):
            result = await self.session.execute(stmt)
            for row in result.scalars().all():
                items.append(
                    {
                        "artifact_kind": kind,
                        "artifact_id": getattr(row, id_field),
                        "project_id": project_id,
                        "created_at": getattr(row, created_field),
                        "is_deleted": getattr(row, deleted_field),
                        "metadata": meta_fn(row),
                    }
                )

        await add_rows(
            select(Document).where(Document.project_id == project_id),
            "document",
            "document_id",
            "created_at",
            "is_deleted",
            lambda r: {"filename": r.filename},
        )
        await add_rows(
            select(DocumentVersion).join(Document, Document.document_id == DocumentVersion.document_id).where(Document.project_id == project_id),
            "document_version",
            "version_id",
            "created_at",
            "is_deleted",
            lambda r: {"document_id": r.document_id, "status": r.status},
        )
        await add_rows(
            select(SegmentSetVersion).where(SegmentSetVersion.project_id == project_id),
            "segment_set",
            "segment_set_version_id",
            "created_at",
            "is_deleted",
            lambda r: {"document_version_id": r.document_version_id, "is_active": r.is_active},
        )
        await add_rows(
            select(ChunkSetVersion).where(ChunkSetVersion.project_id == project_id),
            "chunk_set",
            "chunk_set_version_id",
            "created_at",
            "is_deleted",
            lambda r: {"segment_set_version_id": r.segment_set_version_id, "is_active": r.is_active},
        )
        await add_rows(
            select(Index).where(Index.project_id == project_id),
            "index",
            "index_id",
            "created_at",
            "is_deleted",
            lambda r: {"name": r.name, "provider": r.provider},
        )
        await add_rows(
            select(IndexBuild).where(IndexBuild.project_id == project_id),
            "index_build",
            "build_id",
            "created_at",
            "is_deleted",
            lambda r: {"index_id": r.index_id, "status": r.status, "is_active": r.is_active},
        )
        await add_rows(
            select(GraphBuild).where(GraphBuild.project_id == project_id),
            "graph_build",
            "graph_build_id",
            "created_at",
            "is_deleted",
            lambda r: {"source_type": r.source_type, "source_id": r.source_id, "backend": r.backend, "status": r.status},
        )
        await add_rows(
            select(RetrievalRun).where(RetrievalRun.project_id == project_id),
            "retrieval_run",
            "run_id",
            "created_at",
            "is_deleted",
            lambda r: {"strategy": r.strategy, "target_type": r.target_type},
        )

        items.sort(key=lambda i: i["created_at"], reverse=True)
        return items

    async def soft_delete(self, artifact_id: str, reason: str | None = None) -> dict:
        row, kind, project_id = await self._find_artifact(artifact_id)
        setattr(row, "is_deleted", True)

        deleted = ArtifactSoftDelete(
            project_id=project_id,
            artifact_kind=kind,
            artifact_id=artifact_id,
            reason=reason,
            deleted_at=datetime.now(timezone.utc),
        )
        self.session.add(deleted)
        await self.session.commit()
        return {"artifact_kind": kind, "artifact_id": artifact_id, "deleted_at": deleted.deleted_at}

    async def restore(self, artifact_id: str) -> dict:
        row, kind, project_id = await self._find_artifact(artifact_id, include_deleted=True)
        if not hasattr(row, "is_deleted"):
            raise api_error(400, "artifact_not_soft_deletable", "Artifact does not support soft delete", {"artifact_id": artifact_id})

        setattr(row, "is_deleted", False)

        stmt = (
            select(ArtifactSoftDelete)
            .where(
                ArtifactSoftDelete.artifact_id == artifact_id,
                ArtifactSoftDelete.project_id == project_id,
                ArtifactSoftDelete.artifact_kind == kind,
                ArtifactSoftDelete.restored_at.is_(None),
            )
            .order_by(ArtifactSoftDelete.deleted_at.desc())
        )
        res = await self.session.execute(stmt)
        last = res.scalars().first()
        restored_at = datetime.now(timezone.utc)
        if last:
            last.restored_at = restored_at

        await self.session.commit()
        return {"artifact_kind": kind, "artifact_id": artifact_id, "restored_at": restored_at}

    async def _find_artifact(self, artifact_id: str, include_deleted: bool = False):
        tables = [
            (Document, "document", "project_id", "document_id"),
            (DocumentVersion, "document_version", "document_id", "version_id"),
            (SegmentSetVersion, "segment_set", "project_id", "segment_set_version_id"),
            (ChunkSetVersion, "chunk_set", "project_id", "chunk_set_version_id"),
            (Index, "index", "project_id", "index_id"),
            (IndexBuild, "index_build", "project_id", "build_id"),
            (GraphBuild, "graph_build", "project_id", "graph_build_id"),
            (RetrievalRun, "retrieval_run", "project_id", "run_id"),
        ]

        for model, kind, project_field, pk in tables:
            row = await self.session.get(model, artifact_id)
            if not row:
                continue
            if hasattr(row, "is_deleted") and getattr(row, "is_deleted") and not include_deleted:
                continue

            project_id = getattr(row, project_field)
            if model is DocumentVersion:
                # Resolve project via document.
                doc = await self.session.get(Document, row.document_id)
                if not doc:
                    continue
                project_id = doc.project_id
            return row, kind, project_id

        raise api_error(404, "artifact_not_found", "Artifact not found", {"artifact_id": artifact_id})
