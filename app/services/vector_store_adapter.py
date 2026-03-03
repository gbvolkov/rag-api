from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.errors import api_error


def _provider(index_row) -> str:
    provider = str(index_row.provider or "").strip().lower()
    if provider not in {"qdrant", "faiss", "chroma", "postgres"}:
        raise api_error(501, "provider_unsupported", "Provider is not implemented", {"provider": provider})
    return provider


def _collection_name(index_row) -> str:
    cfg = index_row.config_json or {}
    return str(
        cfg.get(
            "collection_name",
            f"{settings.default_vector_collection_prefix}_{index_row.project_id}_{index_row.index_id}",
        )
    )


def _connection_uri(index_row, provider: str) -> str | None:
    cfg = index_row.config_json or {}
    if provider == "qdrant":
        return settings.qdrant_url
    if provider == "postgres":
        connection = cfg.get("connection") or settings.vector_postgres_connection
        if not connection:
            raise api_error(
                400,
                "missing_index_config",
                "Postgres provider requires connection string",
                {"provider": "postgres"},
            )
        return str(connection)
    return None


def _create_store(*, index_row, embeddings, cleanup: bool):
    provider = _provider(index_row)
    from rag_lib.vectors.factory import create_vector_store

    try:
        return create_vector_store(
            provider=provider,
            embeddings=embeddings,
            collection_name=_collection_name(index_row),
            connection_uri=_connection_uri(index_row, provider),
            cleanup=cleanup,
        )
    except ImportError as exc:
        raise api_error(
            424,
            "missing_dependency",
            "Vector store dependency is not available",
            {"provider": provider, "error": str(exc)},
        ) from exc
    except ValueError as exc:
        message = str(exc)
        if "Unknown Vector Store provider" in message:
            raise api_error(501, "provider_unsupported", "Provider is not implemented", {"provider": provider}) from exc
        raise api_error(
            400,
            "invalid_vector_store_config",
            "Vector store configuration is invalid",
            {"provider": provider, "error": message},
        ) from exc
    except Exception as exc:
        raise api_error(
            424,
            "vector_store_unavailable",
            "Vector store is unavailable",
            {"provider": provider, "error": str(exc)},
        ) from exc


def create_vector_store_for_build(index_row, embeddings):
    return _create_store(index_row=index_row, embeddings=embeddings, cleanup=True)


def create_vector_store_for_retrieval(index_row, embeddings):
    store = _create_store(index_row=index_row, embeddings=embeddings, cleanup=False)
    provider = _provider(index_row)
    cfg = index_row.config_json or {}
    if provider != "faiss":
        return store

    faiss_dir = cfg.get("faiss_local_dir")
    if not faiss_dir:
        raise api_error(
            500,
            "missing_faiss_artifact",
            "FAISS index path is missing from index configuration",
            {"index_id": index_row.index_id},
        )

    load_local = getattr(type(store), "load_local", None)
    if not callable(load_local):
        raise api_error(
            424,
            "vector_store_unavailable",
            "FAISS loader is unavailable in current runtime",
            {"index_id": index_row.index_id},
        )

    try:
        return load_local(str(Path(faiss_dir)), embeddings, allow_dangerous_deserialization=True)
    except Exception as exc:
        raise api_error(
            424,
            "vector_store_unavailable",
            "FAISS index could not be loaded",
            {"index_id": index_row.index_id, "faiss_local_dir": str(faiss_dir), "error": str(exc)},
        ) from exc


def vector_store_manifest(index_row, build_id: str, count: int) -> dict[str, Any]:
    provider = _provider(index_row)
    payload: dict[str, Any] = {
        "provider": provider,
        "index_id": index_row.index_id,
        "build_id": build_id,
        "vectors": int(count),
    }
    cfg = index_row.config_json or {}
    if provider in {"qdrant", "chroma", "postgres"}:
        payload["collection_name"] = _collection_name(index_row)
    if provider == "chroma" and cfg.get("chroma_persist_directory"):
        payload["chroma_persist_directory"] = cfg["chroma_persist_directory"]
    if provider == "faiss" and cfg.get("faiss_local_dir"):
        payload["faiss_local_dir"] = cfg["faiss_local_dir"]
    return payload
