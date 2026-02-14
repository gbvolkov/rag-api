import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
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
