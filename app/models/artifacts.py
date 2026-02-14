from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Document(Base):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.document_id", ondelete="CASCADE"), index=True)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    input_refs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    producer_type: Mapped[str] = mapped_column(String(100), default="kbman_svc")
    producer_version: Mapped[str] = mapped_column(String(100), default="v1")
    status: Mapped[str] = mapped_column(String(50), default="succeeded")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SegmentSetVersion(Base):
    __tablename__ = "segment_set_versions"

    segment_set_version_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), index=True)
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_versions.version_id", ondelete="SET NULL"), index=True)
    parent_segment_set_version_id: Mapped[str | None] = mapped_column(ForeignKey("segment_set_versions.segment_set_version_id", ondelete="SET NULL"), index=True)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    input_refs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    producer_type: Mapped[str] = mapped_column(String(100), default="rag_lib")
    producer_version: Mapped[str] = mapped_column(String(100), default="unknown")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class SegmentItem(Base):
    __tablename__ = "segment_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    segment_set_version_id: Mapped[str] = mapped_column(ForeignKey("segment_set_versions.segment_set_version_id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    parent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    path_json: Mapped[list] = mapped_column(JSON, default=list)
    type: Mapped[str] = mapped_column(String(50), default="text")
    original_format: Mapped[str] = mapped_column(String(50), default="text")


class ChunkSetVersion(Base):
    __tablename__ = "chunk_set_versions"

    chunk_set_version_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), index=True)
    segment_set_version_id: Mapped[str] = mapped_column(ForeignKey("segment_set_versions.segment_set_version_id", ondelete="CASCADE"), index=True)
    parent_chunk_set_version_id: Mapped[str | None] = mapped_column(ForeignKey("chunk_set_versions.chunk_set_version_id", ondelete="SET NULL"), index=True)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    input_refs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    producer_type: Mapped[str] = mapped_column(String(100), default="rag_lib")
    producer_version: Mapped[str] = mapped_column(String(100), default="unknown")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ChunkItem(Base):
    __tablename__ = "chunk_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    chunk_set_version_id: Mapped[str] = mapped_column(ForeignKey("chunk_set_versions.chunk_set_version_id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(String(128), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    parent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    path_json: Mapped[list] = mapped_column(JSON, default=list)
    type: Mapped[str] = mapped_column(String(50), default="text")
    original_format: Mapped[str] = mapped_column(String(50), default="text")


class Index(Base):
    __tablename__ = "indexes"

    index_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    index_type: Mapped[str] = mapped_column(String(50), default="chunk_vectors")
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="created")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class IndexBuild(Base):
    __tablename__ = "index_builds"

    build_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    index_id: Mapped[str] = mapped_column(ForeignKey("indexes.index_id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), index=True)
    chunk_set_version_id: Mapped[str] = mapped_column(ForeignKey("chunk_set_versions.chunk_set_version_id", ondelete="CASCADE"), index=True)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    input_refs_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="queued")
    producer_type: Mapped[str] = mapped_column(String(100), default="rag_lib")
    producer_version: Mapped[str] = mapped_column(String(100), default="unknown")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), index=True)
    strategy: Mapped[str] = mapped_column(String(100), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    results_json: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Job(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="queued")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class ArtifactEvent(Base):
    __tablename__ = "artifact_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), index=True)
    artifact_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ArtifactSoftDelete(Base):
    __tablename__ = "artifact_soft_deletes"

    delete_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id", ondelete="CASCADE"), index=True)
    artifact_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
