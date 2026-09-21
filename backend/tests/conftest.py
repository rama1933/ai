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


@pytest.fixture
def client() -> TestClient:
    from main import create_app

    return TestClient(create_app())
