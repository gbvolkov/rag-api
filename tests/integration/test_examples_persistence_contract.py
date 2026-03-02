from pathlib import Path

from tests.integration.test_examples_modules_api_only import EXAMPLE_FILES, _LocalApiClient, _run_example, _setup_feature_mocks


def test_examples_persist_artifacts_and_retrieval_runs(client, monkeypatch):
    _setup_feature_mocks(monkeypatch)
    local_client = _LocalApiClient(client)
    examples_dir = Path(__file__).resolve().parents[2] / "examples"
    no_retrieval_examples = {
        "17A_web_loader_plantpad.py",
        "17B_web_loader_quotes.py",
        "17C_web_loader_example.py",
        "17_web_loader.py",
    }

    for filename in EXAMPLE_FILES:
        artifacts = _run_example(examples_dir / filename, local_client)
        assert artifacts.get("project_id")
        if filename == "15_pptx_unsupported.py":
            assert artifacts["status"] == "error"
            assert artifacts.get("error_status_code") == 400
            continue

        assert artifacts["status"] == "ok"
        assert artifacts.get("segment_set_version_id")
        if filename in no_retrieval_examples:
            assert not artifacts.get("retrieval_run_ids")
            persisted_runs = local_client.list_retrieval_runs(artifacts["project_id"])
            assert persisted_runs == []
            continue

        run_ids = artifacts.get("retrieval_run_ids", [])
        assert len(run_ids) >= 1
        persisted_runs = local_client.list_retrieval_runs(artifacts["project_id"])
        persisted_run_ids = {r["run_id"] for r in persisted_runs}
        assert all(rid in persisted_run_ids for rid in run_ids)
