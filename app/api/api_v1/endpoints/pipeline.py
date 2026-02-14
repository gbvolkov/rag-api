import json
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.api_v1.deps import require_active_project
from app.db.session import get_session
from app.schemas.pipeline import PipelineRequestMeta, PipelineResponse
from app.services.index_service import IndexService
from app.services.pipeline_service import PipelineService
from app.storage.object_store import object_store
from app.workers.tasks import run_pipeline

router = APIRouter()


@router.post("/projects/{project_id}/pipeline/file", response_model=PipelineResponse)
async def pipeline_file(
    project_id: str,
    file: UploadFile = File(...),
    loader_type: str = Form(...),
    loader_params_json: str | None = Form(default=None),
    chunk_strategy: str = Form(default="recursive"),
    chunker_params_json: str | None = Form(default=None),
    create_index: bool = Form(default=False),
    index_id: str | None = Form(default=None),
    index_params_json: str | None = Form(default=None),
    execution_mode: str = Form(default="sync"),
    _project=Depends(require_active_project),
    session: AsyncSession = Depends(get_session),
):
    loader_params = json.loads(loader_params_json) if loader_params_json else {}
    chunker_params = json.loads(chunker_params_json) if chunker_params_json else {}
    index_params = json.loads(index_params_json) if index_params_json else {}

    req = PipelineRequestMeta(
        loader_type=loader_type,
        loader_params=loader_params,
        chunk_strategy=chunk_strategy,
        chunker_params=chunker_params,
        create_index=create_index,
        index_id=index_id,
        index_params=index_params,
        execution_mode=execution_mode,
    )

    payload = await file.read()

    if execution_mode == "async":
        index_svc = IndexService(session)
        job = await index_svc.create_job(
            project_id=project_id,
            job_type="pipeline",
            payload={"filename": file.filename, "loader_type": loader_type},
        )

        object_key = f"projects/{project_id}/jobs/{job.job_id}/pipeline_input/{file.filename or 'upload.bin'}"
        object_store.put_bytes(object_key, payload, content_type=file.content_type or "application/octet-stream")

        run_pipeline.delay(
            job.job_id,
            project_id,
            file.filename or "upload.bin",
            file.content_type or "application/octet-stream",
            object_key,
            req.model_dump(mode="json"),
        )

        return PipelineResponse(
            project_id=project_id,
            document_id="",
            document_version_id="",
            segment_set_version_id="",
            chunk_set_version_id="",
            index_build_id=None,
            job_id=job.job_id,
            status="queued",
        )

    svc = PipelineService(session)
    out = await svc.run_sync(
        project_id=project_id,
        filename=file.filename or "upload.bin",
        mime=file.content_type or "application/octet-stream",
        payload=payload,
        request=req,
    )

    return PipelineResponse(
        project_id=project_id,
        document_id=out["document"].document_id,
        document_version_id=out["document_version"].version_id,
        segment_set_version_id=out["segment_set"].segment_set_version_id,
        chunk_set_version_id=out["chunk_set"].chunk_set_version_id,
        index_build_id=out["index_build"].build_id if out["index_build"] else None,
        job_id=None,
        status="succeeded",
    )
