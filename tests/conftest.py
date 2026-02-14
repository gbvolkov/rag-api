import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def test_env():
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["OBJECT_STORE_BACKEND"] = "fs"
    os.environ["LOCAL_OBJECT_STORE_PATH"] = f"./.test_artifacts_{uuid4()}"
    os.environ["REDIS_URL"] = "redis://localhost:6379/9"
    os.environ["QDRANT_URL"] = "http://localhost:6333"

    yield


@pytest.fixture
def client(test_env):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def fixture_inputs_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "inputs"
