import hashlib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import api_error
from app.core.mime_utils import normalize_mime
from app.models import Document, DocumentVersion, Project
from app.storage.keys import uri_to_key
from app.storage.object_store import object_store


class DocumentService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_document(self, project_id: str, filename: str, mime: str, payload: bytes, parser_params: dict) -> tuple[Document, DocumentVersion]:
        project = await self.session.get(Project, project_id)
        if not project:
            raise api_error(404, "project_not_found", "Project not found", {"project_id": project_id})

        normalized_mime = normalize_mime(mime)
        content_hash = hashlib.sha256(payload).hexdigest()

        document = Document(
            project_id=project_id,
            filename=filename,
            mime=normalized_mime,
            storage_uri="pending",
            metadata_json={"size": len(payload)},
        )
        self.session.add(document)
        await self.session.flush()

        version = DocumentVersion(
            document_id=document.document_id,
            content_hash=content_hash,
            parser_params_json=parser_params,
            params_json={"source": "upload"},
            input_refs_json={},
            producer_type="rag_api",
            producer_version=settings.rag_lib_producer_version,
        )
        self.session.add(version)
        await self.session.flush()

        key = f"projects/{project_id}/documents/{document.document_id}/{version.version_id}/raw/{filename}"
        uri = object_store.put_bytes(key, payload, content_type=normalized_mime)

        document.storage_uri = uri
        version.artifact_uri = uri

        await self.session.commit()
        await self.session.refresh(document)
        await self.session.refresh(version)
        return document, version

    async def list_documents(self, project_id: str) -> list[Document]:
        stmt = (
            select(Document)
            .where(Document.project_id == project_id, Document.is_deleted.is_(False))
            .order_by(Document.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_document(self, document_id: str) -> Document:
        row = await self.session.get(Document, document_id)
        if not row or row.is_deleted:
            raise api_error(404, "document_not_found", "Document not found", {"document_id": document_id})
        return row

    async def list_versions(self, document_id: str) -> list[DocumentVersion]:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id, DocumentVersion.is_deleted.is_(False))
            .order_by(DocumentVersion.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_version(self, version_id: str) -> DocumentVersion:
        row = await self.session.get(DocumentVersion, version_id)
        if not row or row.is_deleted:
            raise api_error(404, "document_version_not_found", "Document version not found", {"version_id": version_id})
        return row

    async def get_version_content(self, version_id: str) -> tuple[DocumentVersion, Document, bytes]:
        version = await self.get_version(version_id)
        document = await self.session.get(Document, version.document_id)
        if not document or document.is_deleted:
            raise api_error(404, "document_not_found", "Document not found", {"document_id": version.document_id})

        uri = version.artifact_uri or document.storage_uri
        key = uri_to_key(uri)
        try:
            content = object_store.get_bytes(key)
        except Exception:
            raise api_error(
                404,
                "document_content_not_found",
                "Document content not found",
                {"version_id": version_id, "document_id": document.document_id},
            ) from None

        return version, document, content
