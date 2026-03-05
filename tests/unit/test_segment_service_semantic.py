from types import SimpleNamespace

import pytest

from app.services.segment_service import SegmentService


class _FailingSemanticSplitter:
    def split_text(self, _text: str):
        raise LookupError("NLTK tokenizer 'punkt' is required for SemanticChunker")


def test_semantic_split_maps_missing_nltk_lookup_error(monkeypatch):
    service = SegmentService(session=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_build_splitter", lambda strategy, params: _FailingSemanticSplitter())

    source = [SimpleNamespace(content="Alpha. Beta.", metadata={"source": "test"})]
    with pytest.raises(Exception) as exc:
        service._apply_split_strategy(
            source,
            split_strategy="semantic",
            splitter_params={"embedding_provider": "mock"},
        )

    payload = exc.value.detail
    assert payload["code"] == "missing_dependency"
    assert payload["detail"]["strategy"] == "semantic"
    assert "punkt" in payload["detail"]["dependency"]
    assert "nltk.downloader punkt punkt_tab" in payload["hint"]
