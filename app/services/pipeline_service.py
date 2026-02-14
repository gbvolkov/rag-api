from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.pipeline import PipelineRequestMeta
from app.services.chunk_service import ChunkService
from app.services.document_service import DocumentService
from app.services.index_service import IndexService
from app.services.segment_service import SegmentService


class PipelineService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.documents = DocumentService(session)
        self.segments = SegmentService(session)
        self.chunks = ChunkService(session)
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
            source_text=None,
        )

        chunk_set = await self.chunks.create_from_segment_set(
            segment_set_id=segment_set.segment_set_version_id,
            strategy=request.chunk_strategy,
            chunker_params=request.chunker_params,
        )

        index_build = None
        if request.create_index and request.index_id:
            build = await self.indexes.create_build(
                index_id=request.index_id,
                chunk_set_version_id=chunk_set.chunk_set_version_id,
                params=request.index_params,
                status="queued",
            )
            index_build = await self.indexes.run_build(build.build_id)

        return {
            "document": document,
            "document_version": doc_version,
            "segment_set": segment_set,
            "chunk_set": chunk_set,
            "index_build": index_build,
        }
