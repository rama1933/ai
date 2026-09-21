import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://rag_app:rag_app_pw@localhost:5432/agentic_rag_test")
os.environ.setdefault("DATABASE_URL_READONLY", "postgresql+psycopg2://rag_readonly:rag_readonly_pw@localhost:5432/agentic_rag_test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")


@pytest.fixture(scope="session", autouse=True)
def _test_database_only() -> None:
    """`setdefault` above cannot defend against an exported DATABASE_URL, and the
    suite deletes rows. Refuse to run anywhere but a `_test` database."""
    url = os.environ["DATABASE_URL"].split("?")[0].rstrip("/")
    assert url.endswith("_test"), f"refusing to run the suite against a non-test database: {url}"


@pytest.fixture
def client() -> TestClient:
    from main import create_app

    return TestClient(create_app())
