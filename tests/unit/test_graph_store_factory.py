import pytest

from app.services.graph_service import GraphService


def test_graph_service_rejects_invalid_backend():
    svc = GraphService(session=None)  # type: ignore[arg-type]

    with pytest.raises(Exception) as exc:
        svc._create_graph_store("invalid-backend")

    err = exc.value
    assert getattr(err, "status_code", None) == 400
    assert err.detail["code"] == "invalid_graph_backend"


def test_graph_service_maps_missing_dependency(monkeypatch):
    svc = GraphService(session=None)  # type: ignore[arg-type]

    def _raise_import(*args, **kwargs):
        raise ImportError("neo4j missing")

    monkeypatch.setattr("rag_lib.graph.store.create_graph_store", _raise_import)

    with pytest.raises(Exception) as exc:
        svc._create_graph_store("neo4j")

    err = exc.value
    assert getattr(err, "status_code", None) == 424
    assert err.detail["code"] == "missing_dependency"


def test_graph_service_maps_invalid_backend_config(monkeypatch):
    svc = GraphService(session=None)  # type: ignore[arg-type]

    def _raise_value(*args, **kwargs):
        raise ValueError("bad config")

    monkeypatch.setattr("rag_lib.graph.store.create_graph_store", _raise_value)

    with pytest.raises(Exception) as exc:
        svc._create_graph_store("neo4j")

    err = exc.value
    assert getattr(err, "status_code", None) == 400
    assert err.detail["code"] == "invalid_graph_backend_config"


def test_graph_service_delegates_to_rag_lib_factory(monkeypatch):
    svc = GraphService(session=None)  # type: ignore[arg-type]
    called = {}

    class _Store:
        pass

    def _fake_create_graph_store(**kwargs):
        called.update(kwargs)
        return _Store()

    monkeypatch.setattr("rag_lib.graph.store.create_graph_store", _fake_create_graph_store)

    store, backend = svc._create_graph_store("networkx")
    assert backend == "networkx"
    assert isinstance(store, _Store)
    assert called["provider"] == "networkx"
