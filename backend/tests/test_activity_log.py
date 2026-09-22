"""SP2 Task 1: the activity_log table, its round-trip, and its privileges.

Cleanup follows tests/test_auth.py:14-27 -- uuid-suffixed names, only the rows
this module made.
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from database import SessionLocal, get_readonly_engine
from models import ActivityLog, User


@pytest.fixture
def a_user():
    session = SessionLocal()
    username = f"log-{uuid.uuid4().hex[:8]}"
    user = User(username=username, password_hash="not-a-real-hash", role="USER")
    session.add(user)
    session.commit()
    user_id = user.id
    session.close()
    yield user_id, username
    session = SessionLocal()
    session.query(ActivityLog).filter_by(username=username).delete(synchronize_session=False)
    session.query(User).filter_by(id=user_id).delete(synchronize_session=False)
    session.commit()
    session.close()


def test_activity_log_row_round_trips(a_user):
    user_id, username = a_user
    session = SessionLocal()
    row = ActivityLog(
        user_id=user_id,
        username=username,
        action="AUTH_LOGIN",
        target=None,
        detail={"tool_used": "rag_search"},
    )
    session.add(row)
    session.commit()
    row_id = row.id
    session.close()

    session = SessionLocal()
    stored = session.query(ActivityLog).filter_by(id=row_id).one()
    session.close()
    assert (stored.user_id, stored.username, stored.action) == (user_id, username, "AUTH_LOGIN")
    assert stored.detail == {"tool_used": "rag_search"}
    assert stored.created_at is not None


def test_deleting_a_user_keeps_the_username_snapshot(a_user):
    """The FK nulls out; the log must still name who acted."""
    user_id, username = a_user
    session = SessionLocal()
    session.add(ActivityLog(user_id=user_id, username=username, action="AUTH_LOGIN"))
    session.commit()
    session.query(User).filter_by(id=user_id).delete(synchronize_session=False)
    session.commit()

    stored = session.query(ActivityLog).filter_by(username=username).one()
    session.close()
    assert stored.user_id is None
    assert stored.username == username


def test_rag_readonly_cannot_read_activity_log():
    """The grant is the boundary. The log names every account and every admin
    action, and the SQL tool's reach is LLM-visible, so rag_readonly must hold
    nothing on this table -- now or after any future edit to db/schema.sql."""
    engine = get_readonly_engine()
    with pytest.raises(ProgrammingError, match="permission denied"):
        with engine.connect() as conn:
            conn.execute(text("SELECT * FROM activity_log LIMIT 1"))
