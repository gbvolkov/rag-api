from pathlib import Path

from tests.integration.test_examples_modules_api_only import EXAMPLE_FILES, _LocalApiClient, _run_example, _setup_feature_mocks


def test_examples_output_structure(client, monkeypatch, capsys):
    _setup_feature_mocks(monkeypatch)
    local_client = _LocalApiClient(client)
    examples_dir = Path(__file__).resolve().parents[2] / "examples"

    for filename in EXAMPLE_FILES:
        _run_example(examples_dir / filename, local_client)
        out = capsys.readouterr().out
        assert "1. Create project" in out
        assert "Artifacts saved" in out
        assert "Artifacts" in out

