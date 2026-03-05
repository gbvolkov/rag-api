from types import SimpleNamespace

from app.services.segment_service import SegmentService


def test_regex_hierarchy_accepts_json_list_patterns():
    service = SegmentService(session=None)  # type: ignore[arg-type]

    source = [
        SimpleNamespace(
            content="# Top\nIntro line\n## Child\nChild details\n",
            metadata={"source": "test"},
        )
    ]

    result = service._apply_split_strategy(
        source,
        split_strategy="regex_hierarchy",
        splitter_params={
            "patterns": [
                [1, r"^\s*#\s+(.+)$"],
                [2, r"^\s*##\s+(.+)$"],
            ],
            "include_parent_content": False,
        },
    )

    assert len(result) >= 2
    titles = [segment.metadata.get("title") for segment in result]
    assert "Top" in titles
    assert "Child" in titles
