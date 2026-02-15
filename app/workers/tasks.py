import asyncio

from app.db.session import SessionLocal
from app.schemas.pipeline import PipelineRequestMeta
from app.services.index_service import IndexService
from app.services.job_service import JobService
from app.services.graph_service import GraphService
from app.services.pipeline_service import PipelineService
from app.services.segment_service import SegmentService
from app.services.segment_transform_service import SegmentTransformService
from app.storage.object_store import object_store
from app.workers.celery_app import celery_app


async def _update_job(job_id: str, status: str, result: dict | None = None, error: str | None = None) -> None:
    async with SessionLocal() as session:
        svc = JobService(session)
        await svc.update_status(job_id=job_id, status=status, result_json=result, error_message=error)


@celery_app.task(name="app.workers.tasks.run_index_build")
def run_index_build(job_id: str, build_id: str) -> dict:
    async def _run() -> dict:
        await _update_job(job_id, "running")
        async with SessionLocal() as session:
            svc = IndexService(session)
            build = await svc.run_build(build_id)
            payload = {
                "build_id": build.build_id,
                "index_id": build.index_id,
                "status": build.status,
                "artifact_uri": build.artifact_uri,
            }
            await _update_job(job_id, "succeeded", result=payload)
            return payload

    try:
        return asyncio.run(_run())
    except Exception as exc:
        asyncio.run(_update_job(job_id, "failed", error=str(exc)))
        raise


@celery_app.task(name="app.workers.tasks.run_pipeline")
def run_pipeline(
    job_id: str,
    project_id: str,
    filename: str,
    mime: str,
    payload_object_key: str,
    pipeline_request: dict,
) -> dict:
    async def _run() -> dict:
        await _update_job(job_id, "running")
        raw = object_store.get_bytes(payload_object_key)

        async with SessionLocal() as session:
            svc = PipelineService(session)
            result = await svc.run_sync(
                project_id=project_id,
                filename=filename,
                mime=mime,
                payload=raw,
                request=PipelineRequestMeta(**pipeline_request),
            )
            payload = {
                "document_id": result["document"].document_id,
                "document_version_id": result["document_version"].version_id,
                "segment_set_version_id": result["segment_set"].segment_set_version_id,
                "chunk_set_version_id": result["chunk_set"].chunk_set_version_id,
                "index_build_id": result["index_build"].build_id if result["index_build"] else None,
            }
            await _update_job(job_id, "succeeded", result=payload)
            return payload

    try:
        return asyncio.run(_run())
    except Exception as exc:
        asyncio.run(_update_job(job_id, "failed", error=str(exc)))
        raise


@celery_app.task(name="app.workers.tasks.run_graph_build")
def run_graph_build(job_id: str, graph_build_id: str) -> dict:
    async def _run() -> dict:
        await _update_job(job_id, "running")
        async with SessionLocal() as session:
            svc = GraphService(session)
            build = await svc.run_build(graph_build_id)
            payload = {
                "graph_build_id": build.graph_build_id,
                "project_id": build.project_id,
                "status": build.status,
                "artifact_uri": build.artifact_uri,
            }
            await _update_job(job_id, "succeeded", result=payload)
            return payload

    try:
        return asyncio.run(_run())
    except Exception as exc:
        asyncio.run(_update_job(job_id, "failed", error=str(exc)))
        raise


@celery_app.task(name="app.workers.tasks.run_segment_enrich")
def run_segment_enrich(job_id: str, segment_set_id: str, params: dict) -> dict:
    async def _run() -> dict:
        await _update_job(job_id, "running")
        async with SessionLocal() as session:
            seg_svc = SegmentService(session)
            svc = SegmentTransformService(seg_svc)
            out = await svc.enrich(
                segment_set_id=segment_set_id,
                llm_provider=params.get("llm_provider"),
                llm_model=params.get("llm_model"),
                llm_temperature=params.get("llm_temperature"),
                params=params.get("params", {}),
            )
            payload = {
                "segment_set_version_id": out.segment_set_version_id,
                "parent_segment_set_version_id": out.parent_segment_set_version_id,
                "status": "succeeded",
            }
            await _update_job(job_id, "succeeded", result=payload)
            return payload

    try:
        return asyncio.run(_run())
    except Exception as exc:
        asyncio.run(_update_job(job_id, "failed", error=str(exc)))
        raise


@celery_app.task(name="app.workers.tasks.run_segment_raptor")
def run_segment_raptor(job_id: str, segment_set_id: str, params: dict) -> dict:
    async def _run() -> dict:
        await _update_job(job_id, "running")
        async with SessionLocal() as session:
            seg_svc = SegmentService(session)
            svc = SegmentTransformService(seg_svc)
            out = await svc.raptor(
                segment_set_id=segment_set_id,
                max_levels=int(params.get("max_levels", 3)),
                llm_provider=params.get("llm_provider"),
                llm_model=params.get("llm_model"),
                llm_temperature=params.get("llm_temperature"),
                embedding_provider=params.get("embedding_provider", "openai"),
                embedding_model_name=params.get("embedding_model_name"),
                params=params.get("params", {}),
            )
            payload = {
                "segment_set_version_id": out.segment_set_version_id,
                "parent_segment_set_version_id": out.parent_segment_set_version_id,
                "status": "succeeded",
            }
            await _update_job(job_id, "succeeded", result=payload)
            return payload

    try:
        return asyncio.run(_run())
    except Exception as exc:
        asyncio.run(_update_job(job_id, "failed", error=str(exc)))
        raise
