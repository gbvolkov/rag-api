from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngestionRun
from app.schemas.pipeline import PipelineRequestMeta
from app.services.document_service import DocumentService
from app.services.index_service import IndexService
from app.services.segment_service import SegmentService


class PipelineService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.documents = DocumentService(session)
        self.segments = SegmentService(session)
        self.indexes = IndexService(session)

    async def run_sync(self, project_id: str, filename: str, mime: str, payload: bytes, request: PipelineRequestMeta):
        document, doc_version = await self.documents.create_document(
            project_id=project_id,
            filename=filename,
            mime=mime,
            payload=payload,
            parser_params={"loader_type": request.loader_type, **request.loader_params},
        )

        segment_set = await self.segments.create_from_document_version(
            version_id=doc_version.version_id,
            loader_type=request.loader_type,
            loader_params=request.loader_params,
            split_strategy=None,
            splitter_params={},
            source_text=None,
        )

        source_set = await self.segments.split_from_segment_set(
            segment_set_id=segment_set.segment_set_version_id,
            strategy=request.split_strategy,
            splitter_params=request.splitter_params,
            params={},
        )

        index_build = None
        if request.create_index and request.index_id:
            build = await self.indexes.create_build(
                index_id=request.index_id,
                source_set_id=source_set.segment_set_version_id,
                parent_set_id=None,
                id_key=None,
                params=request.index_params,
                status="queued",
            )
            index_build = await self.indexes.run_build(build.build_id)

        self.session.add(
            IngestionRun(
                project_id=project_id,
                run_type="pipeline_file",
                source_type="document",
                source_id=doc_version.version_id,
                params_json=request.model_dump(mode="json"),
                result_json={
                    "document_version_id": doc_version.version_id,
                    "segment_set_version_id": segment_set.segment_set_version_id,
                    "source_set_id": source_set.segment_set_version_id,
                    "index_build_id": index_build.build_id if index_build else None,
                },
                status="succeeded",
            )
        )
        await self.session.commit()

        return {
            "document": document,
            "document_version": doc_version,
            "segment_set": segment_set,
            "source_set": source_set,
            "index_build": index_build,
        }
