from app.schemas.retrieval import RetrieveRequest


def test_graph_strategy_accepts_mix_mode():
    payload = {
        "query": "alpha",
        "target": "segment_set",
        "target_id": "s1",
        "strategy": {"type": "graph", "graph_build_id": "g1", "mode": "mix"},
    }
    parsed = RetrieveRequest(**payload)
    assert parsed.strategy.mode == "mix"
