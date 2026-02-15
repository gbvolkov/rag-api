import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.core.mime_utils import effective_preview_mime
from app.db.session import get_session
from app.schemas.document import DocumentOut, DocumentVersionOut
from app.services.document_service import DocumentService
from app.services.serializers import document_out, document_version_out

router = APIRouter()


@router.post("/projects/{project_id}/documents")
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    parser_params_json: str | None = Form(default=None),
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    parser_params = json.loads(parser_params_json) if parser_params_json else {}
    payload = await file.read()

    svc = DocumentService(session)
    doc, version = await svc.create_document(
        project_id=project_id,
        filename=file.filename or "upload.bin",
        mime=file.content_type or "application/octet-stream",
        payload=payload,
        parser_params=parser_params,
    )

    return {
        "document": document_out(doc).model_dump(),
        "document_version": document_version_out(version).model_dump(),
    }


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: str,
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    svc = DocumentService(session)
    rows = await svc.list_documents(project_id)
    return [document_out(r) for r in rows]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: str, session: AsyncSession = Depends(get_session)):
    svc = DocumentService(session)
    row = await svc.get_document(document_id)
    return document_out(row)


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_document_versions(document_id: str, session: AsyncSession = Depends(get_session)):
    svc = DocumentService(session)
    rows = await svc.list_versions(document_id)
    return [document_version_out(r) for r in rows]


@router.get("/document_versions/{version_id}/content")
async def get_document_version_content(version_id: str, session: AsyncSession = Depends(get_session)):
    svc = DocumentService(session)
    version, document, content = await svc.get_version_content(version_id)
    mime = effective_preview_mime(document.mime, document.filename)
    quoted_name = quote(document.filename, safe="")
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{quoted_name}",
        "ETag": f'"{version.content_hash}"',
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=content, media_type=mime, headers=headers)
