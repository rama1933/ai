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
from models import ChatHistory, ChatSession, User

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


def _username_of(headers: dict[str, str]) -> str:
    """Recover the username a test's headers belong to.

    A JWT's subject is the username, so read it back rather than threading a
    second value through every fixture.
    """
    import base64
    import json as _json

    payload = headers["Authorization"].split(" ", 1)[1].split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return _json.loads(base64.urlsafe_b64decode(padded))["sub"]


def test_migration_001_is_idempotent():
    """The migration must be a no-op on a database that already carries its schema."""
    first = _psql("-f", MIGRATION)
    assert first.returncode == 0, first.stderr

    second = _psql("-f", MIGRATION)
    assert second.returncode == 0, second.stderr

    # The two returncode assertions above cannot catch the defect this test exists for:
    # the original name-keyed FK guard added a SECOND, differently-named foreign key on
    # the same column and still exited 0. Only counting the FKs detects that.
    fk_count = _psql(
        "-tAc",
        "SELECT count(*) FROM pg_constraint c "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        "WHERE c.conrelid = 'chat_history'::regclass AND c.contype = 'f' "
        "AND a.attname = 'session_id'",
    )
    assert fk_count.returncode == 0, fk_count.stderr
    assert fk_count.stdout.strip() == "1", fk_count.stdout


@pytest.fixture
def two_users(client):
    """Two real accounts, plus the auth headers for each. Yields (headers_a, headers_b)."""
    made = []
    for _ in range(2):
        username = f"own-{uuid.uuid4().hex[:8]}"
        client.post("/auth/register", json={"username": username, "password": "supersecret1"})
        token = client.post("/auth/login", json={"username": username, "password": "supersecret1"}).json()[
            "access_token"
        ]
        made.append({"Authorization": f"Bearer {token}"})
    yield made[0], made[1]
    session = SessionLocal()
    session.query(User).filter(User.username.like("own-%")).delete(synchronize_session=False)
    session.commit()
    session.close()


@pytest.fixture
def quiet_agent(monkeypatch):
    """Replace the live LLM call so these tests need no Ollama."""
    from agent.orchestrator import AgentResult
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router,
        "run_agent",
        lambda db, message, history, image_path: AgentResult(answer="ok", tool_used=None, sources=[]),
    )


def test_chat_creates_session_owned_by_caller(client, two_users, quiet_agent):
    headers_a, _ = two_users
    session_id = f"own-{uuid.uuid4().hex[:8]}"

    response = client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "halo"})

    assert response.status_code == 200
    session = SessionLocal()
    row = session.query(ChatSession).filter_by(id=session_id).one()
    owner = session.query(User).filter_by(username=_username_of(headers_a)).one()
    session.close()
    assert row.user_id == owner.id


def test_chat_rejects_foreign_session_id(client, two_users, quiet_agent):
    """User B must not be able to write into user A's conversation."""
    headers_a, headers_b = two_users
    session_id = f"own-{uuid.uuid4().hex[:8]}"
    client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "rahasia A"})

    response = client.post("/chat", headers=headers_b, json={"session_id": session_id, "message": "halo dari B"})

    assert response.status_code == 404
    session = SessionLocal()
    rows = session.query(ChatHistory).filter_by(session_id=session_id).all()
    session.close()
    assert [r.message for r in rows] == ["rahasia A", "ok"], "B's message must not have been written"


def test_history_is_isolated_between_users(client, two_users, quiet_agent):
    """The IDOR regression: reading another user's conversation returns 404, not content."""
    headers_a, headers_b = two_users
    session_id = f"own-{uuid.uuid4().hex[:8]}"
    client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "rahasia A"})

    response = client.get(f"/chat/history?session_id={session_id}", headers=headers_b)

    assert response.status_code == 404
    assert "rahasia A" not in response.text


def test_history_requires_existing_session(client, two_users, quiet_agent):
    """An unknown id is 404, not an empty list -- the two must be indistinguishable."""
    headers_a, _ = two_users

    response = client.get(f"/chat/history?session_id=own-{uuid.uuid4().hex[:8]}", headers=headers_a)

    assert response.status_code == 404


def test_chat_second_message_reuses_the_same_session(client, two_users, quiet_agent):
    """Regression: both INSERTs are pending in one flush and SQLAlchemy orders them by
    class name, so without an explicit flush in get_or_create_session the chat_history
    INSERT is emitted first and every message on a new session fails on the foreign key."""
    headers_a, _ = two_users
    session_id = f"own-{uuid.uuid4().hex[:8]}"

    first = client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "satu"})
    second = client.post("/chat", headers=headers_a, json={"session_id": session_id, "message": "dua"})

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text


def test_auth_me_returns_username_and_role(client, two_users):
    headers_a, _ = two_users

    response = client.get("/auth/me", headers=headers_a)

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == _username_of(headers_a)
    assert body["role"] == "USER"
    assert body["created_at"]


def test_auth_me_rejects_missing_token(client):
    assert client.get("/auth/me").status_code == 401
