import pytest

from app.core.capabilities import require_choice, require_feature, require_module


def test_require_feature_raises_when_disabled():
    with pytest.raises(Exception) as exc:
        require_feature(False, "graph")
    payload = exc.value.detail
    assert payload["code"] == "capability_disabled"
    assert payload["detail"]["feature"] == "graph"


def test_require_module_raises_when_missing():
    with pytest.raises(Exception) as exc:
        require_module("module_that_does_not_exist_xyz", "x")
    payload = exc.value.detail
    assert payload["code"] == "missing_dependency"
    assert payload["detail"]["module"] == "module_that_does_not_exist_xyz"


def test_require_choice_raises_for_invalid_value():
    with pytest.raises(Exception) as exc:
        require_choice("bad", {"a", "b"}, code="bad_choice", message="invalid", field="value")
    payload = exc.value.detail
    assert payload["code"] == "bad_choice"
    assert payload["detail"]["value"] == "bad"

