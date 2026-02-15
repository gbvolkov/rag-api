from app.schemas.retrieval import RetrieveRequest


def test_graph_strategy_schema_parses():
    payload = {
        "query": "alpha",
        "target": "graph_build",
        "strategy": {"type": "graph", "graph_build_id": "g1", "mode": "local", "search_depth": 2},
    }
    parsed = RetrieveRequest(**payload)
    assert parsed.strategy.type == "graph"
    assert parsed.strategy.graph_build_id == "g1"


def test_graph_hybrid_strategy_schema_parses():
    payload = {
        "query": "alpha",
        "target": "index_build",
        "target_id": "b1",
        "strategy": {
            "type": "graph_hybrid",
            "graph_build_id": "g1",
            "mode": "global",
            "vector": {"k": 5, "search_type": "similarity"},
            "weights": [0.6, 0.4],
        },
    }
    parsed = RetrieveRequest(**payload)
    assert parsed.strategy.type == "graph_hybrid"
    assert parsed.strategy.graph_build_id == "g1"
    assert parsed.strategy.vector["k"] == 5

