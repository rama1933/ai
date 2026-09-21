"""Ownership guarantees introduced by SP0.

Every test here builds its own users with uuid-suffixed names and removes them
afterwards, following the convention in tests/test_auth.py:10-24. Deleting a
User cascades to sessions and then to chat_history, so cleanup needs no
per-table bookkeeping.
"""
import subprocess
import uuid

import pytest

from database import SessionLocal
from models import User

PSQL = "/opt/homebrew/opt/postgresql@17/bin/psql"
TEST_DB = "agentic_rag_test"
MIGRATION = "db/migrations/001_ownership.sql"


def _psql(*args: str, db: str = TEST_DB) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PSQL, "-d", db, "-v", "ON_ERROR_STOP=1", *args],
        cwd="..",
        capture_output=True,
        text=True,
    )


def test_migration_001_is_idempotent():
    """The migration must be a no-op on a database that already carries its schema."""
    first = _psql("-f", MIGRATION)
    assert first.returncode == 0, first.stderr

    second = _psql("-f", MIGRATION)
    assert second.returncode == 0, second.stderr

    count = _psql("-tAc", "SELECT count(*) FROM sessions")
    assert count.returncode == 0, count.stderr
