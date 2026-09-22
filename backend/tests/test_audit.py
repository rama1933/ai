"""SP2 Task 2: the audit helper and the call sites that use it."""
import uuid

import pytest

from sqlalchemy import text

from database import SessionLocal
from models import ActivityLog, User

# A failed login has no account to name, so its attempted username lives in detail
# and its username column is null. Both spellings have to match for cleanup and for
# the reads below, or the rows this module made become invisible to it.
MINE = text("username LIKE 'audit-%' OR detail->>'username' LIKE 'audit-%'")


@pytest.fixture
def fresh_username() -> str:
    return f"audit-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup_audit_rows():
    """Only this module's rows. activity_log survives its user (ON DELETE SET NULL),
    so it cannot ride the user deletion the way test_auth.py's cleanup does."""
    yield
    session = SessionLocal()
    session.query(ActivityLog).filter(MINE).delete(synchronize_session=False)
    session.query(User).filter(User.username.like("audit-%")).delete(synchronize_session=False)
    session.commit()
    session.close()


def _rows(action: str) -> list[ActivityLog]:
    session = SessionLocal()
    rows = session.query(ActivityLog).filter(ActivityLog.action == action).filter(MINE).all()
    session.close()
    return rows


def test_register_then_login_writes_one_auth_login_row(client, fresh_username):
    client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    client.post("/auth/login", json={"username": fresh_username, "password": "supersecret1"})

    rows = _rows("AUTH_LOGIN")
    assert len(rows) == 1, "exactly one row per successful login"
    assert rows[0].username == fresh_username
    assert rows[0].user_id is not None
    assert _rows("AUTH_REGISTER")[0].target is None


def test_failed_login_records_the_attempted_username(client, fresh_username):
    client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    denied = client.post("/auth/login", json={"username": fresh_username, "password": "wrongpassword"})
    assert denied.status_code == 401

    rows = _rows("AUTH_LOGIN_FAILED")
    assert len(rows) == 1
    assert rows[0].user_id is None, "there is no authenticated actor to name"
    assert rows[0].detail["username"] == fresh_username


def test_unknown_username_failure_is_logged_too(client, fresh_username):
    client.post("/auth/login", json={"username": fresh_username, "password": "supersecret1"})

    rows = _rows("AUTH_LOGIN_FAILED")
    assert [row.detail["username"] for row in rows] == [fresh_username]


def test_chat_turn_records_the_tool_and_no_message_text(client, fresh_username, monkeypatch):
    from agent.orchestrator import AgentResult
    from routers import chat as chat_router

    secret = "rahasia yang tidak boleh masuk log"
    monkeypatch.setattr(
        chat_router,
        "run_agent",
        lambda db, message, history, image_paths, document_filenames=None: AgentResult(
            answer="ok", tool_used="rag_search", sources=[]
        ),
    )
    client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    token = client.post("/auth/login", json={"username": fresh_username, "password": "supersecret1"}).json()[
        "access_token"
    ]
    session_id = f"audit-{uuid.uuid4().hex[:8]}"

    response = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id, "message": secret},
    )
    assert response.status_code == 200, response.text

    rows = _rows("CHAT_TURN")
    assert len(rows) == 1
    assert rows[0].target == session_id
    assert rows[0].detail["tool_used"] == "rag_search"
    assert rows[0].detail["chars_in"] == len(secret)
    assert rows[0].detail["chars_out"] == 2
    assert "message" not in rows[0].detail, "the log holds metadata, never content"
    assert secret not in str(rows[0].detail)
