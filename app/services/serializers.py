from app.models import (
    Document,
    DocumentVersion,
    GraphBuild,
    Index,
    IndexBuild,
    Job,
    Project,
    RetrievalRun,
    SegmentItem,
    SegmentSetVersion,
)
from app.core.errors import api_error
from app.schemas.document import DocumentOut, DocumentVersionOut
from app.schemas.graph import GraphBuildOut
from app.schemas.indexing import IndexBuildDocStoreOut, IndexBuildOut, IndexOut
from app.schemas.job import JobOut
from app.schemas.project import ProjectOut, ProjectSettings
from app.schemas.retrieval import RetrievalRunOut
from app.schemas.segment import SegmentItemOut, SegmentSetOut, SegmentType


def project_out(m: Project) -> ProjectOut:
    return ProjectOut(
        project_id=m.project_id,
        name=m.name,
        description=m.description,
        settings=ProjectSettings(**(m.settings_json or {})),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def document_out(m: Document) -> DocumentOut:
    return DocumentOut(
        document_id=m.document_id,
        project_id=m.project_id,
        filename=m.filename,
        mime=m.mime,
        storage_uri=m.storage_uri,
        metadata=m.metadata_json or {},
        is_deleted=m.is_deleted,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def document_version_out(m: DocumentVersion) -> DocumentVersionOut:
    return DocumentVersionOut(
        version_id=m.version_id,
        document_id=m.document_id,
        content_hash=m.content_hash,
        parser_params=m.parser_params_json or {},
        params=m.params_json or {},
        input_refs=m.input_refs_json or {},
        artifact_uri=m.artifact_uri,
        producer_type=m.producer_type,
        producer_version=m.producer_version,
        status=m.status,
        is_active=m.is_active,
        is_deleted=m.is_deleted,
        created_at=m.created_at,
    )


def segment_set_out(m: SegmentSetVersion, total_items: int = 0) -> SegmentSetOut:
    return SegmentSetOut(
        segment_set_version_id=m.segment_set_version_id,
        project_id=m.project_id,
        document_version_id=m.document_version_id,
        parent_segment_set_version_id=m.parent_segment_set_version_id,
        params=m.params_json or {},
        input_refs=m.input_refs_json or {},
        artifact_uri=m.artifact_uri,
        producer_type=m.producer_type,
        producer_version=m.producer_version,
        is_active=m.is_active,
        is_deleted=m.is_deleted,
        created_at=m.created_at,
        total_items=total_items,
    )


def segment_item_out(m: SegmentItem) -> SegmentItemOut:
    try:
        seg_type = SegmentType(m.type)
    except Exception as exc:
        raise api_error(
            500,
            "invalid_segment_type",
            "Persisted segment item type is invalid",
            {"item_id": m.item_id, "type": m.type, "allowed": [e.value for e in SegmentType]},
        ) from exc
    return SegmentItemOut(
        item_id=m.item_id,
        position=m.position,
        content=m.content,
        metadata=m.metadata_json or {},
        parent_id=m.parent_id,
        level=m.level,
        path=m.path_json or [],
        type=seg_type,
        original_format=m.original_format,
    )


def index_out(m: Index) -> IndexOut:
    return IndexOut(
        index_id=m.index_id,
        project_id=m.project_id,
        name=m.name,
        provider=m.provider,
        index_type=m.index_type,
        config=m.config_json or {},
        params=m.params_json or {},
        status=m.status,
        is_deleted=m.is_deleted,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def index_build_out(m: IndexBuild) -> IndexBuildOut:
    raw_doc_store = (m.input_refs_json or {}).get("doc_store")
    doc_store = None
    if isinstance(raw_doc_store, dict):
        try:
            doc_store = IndexBuildDocStoreOut(**raw_doc_store)
        except Exception as exc:
            raise api_error(
                500,
                "invalid_doc_store_manifest",
                "Index build doc_store metadata is invalid",
                {"build_id": m.build_id},
            ) from exc
    return IndexBuildOut(
        build_id=m.build_id,
        index_id=m.index_id,
        project_id=m.project_id,
        source_set_id=m.source_set_id,
        parent_set_id=m.parent_set_id,
        id_key=(m.input_refs_json or {}).get("id_key"),
        params=m.params_json or {},
        input_refs=m.input_refs_json or {},
        artifact_uri=m.artifact_uri,
        doc_store=doc_store,
        status=m.status,
        producer_type=m.producer_type,
        producer_version=m.producer_version,
        is_active=m.is_active,
        is_deleted=m.is_deleted,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def graph_build_out(m: GraphBuild) -> GraphBuildOut:
    return GraphBuildOut(
        graph_build_id=m.graph_build_id,
        project_id=m.project_id,
        source_type=m.source_type,
        source_id=m.source_id,
        backend=m.backend,
        params=m.params_json or {},
        input_refs=m.input_refs_json or {},
        artifact_uri=m.artifact_uri,
        status=m.status,
        producer_type=m.producer_type,
        producer_version=m.producer_version,
        is_active=m.is_active,
        is_deleted=m.is_deleted,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def retrieval_run_out(m: RetrievalRun) -> RetrievalRunOut:
    return RetrievalRunOut(
        run_id=m.run_id,
        project_id=m.project_id,
        strategy=m.strategy,
        query=m.query,
        target_type=m.target_type,
        target_id=m.target_id,
        params=m.params_json or {},
        results=m.results_json or {},
        artifact_uri=m.artifact_uri,
        is_deleted=m.is_deleted,
        created_at=m.created_at,
    )


def job_out(m: Job) -> JobOut:
    return JobOut(
        job_id=m.job_id,
        project_id=m.project_id,
        job_type=m.job_type,
        status=m.status,
        payload=m.payload_json or {},
        result=m.result_json or {},
        error_message=m.error_message,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )
