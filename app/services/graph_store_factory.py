from __future__ import annotations

from app.core.capabilities import module_available, require_choice, require_module
from app.core.config import settings


def create_graph_store(backend: str | None = None):
    resolved = (backend or settings.graph_backend_default).lower()
    require_choice(
        resolved,
        {"neo4j", "networkx"},
        code="invalid_graph_backend",
        message="Unsupported graph backend",
        field="backend",
    )

    if resolved == "neo4j":
        if not module_available("neo4j") and settings.environment.lower() in {"dev", "local", "test"}:
            resolved = "networkx"
        else:
            require_module("neo4j", "graph_backend_neo4j", install_hint="Install optional dependency 'neo4j'.")
    if resolved == "neo4j":
        from rag_lib.graph.neo4j_store import Neo4jGraphStore

        return Neo4jGraphStore(
            uri=settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            database=settings.neo4j_database,
        ), resolved

    from rag_lib.graph.store import NetworkXGraphStore

    return NetworkXGraphStore(), resolved
