"""The one place that writes an activity_log row.

Every row records WHAT HAPPENED, never WHAT WAS SAID: action, actor, target and a
small JSONB detail (tool used, duration, chunk count, message length). Message text
is deliberately absent -- SP2 Decision 3.

The helper does not commit. It rides the request's unit of work like every other
write in this codebase, so a request that rolls back leaves no audit row claiming
it succeeded. The streaming chat turn is the one exception, and there it is called
on the same SessionLocal that persists the assistant row, for the same reason.

ponytail: a failed login is written from an unauthenticated endpoint, so it is an
unbounded row source -- one row per attempt, including attempts by anything that
can reach the port. Ceiling: a single-operator install. The release valve is
DELETE /admin/logs?before=<date> (admin.py); if this ever leaves localhost, throttle
the login route rather than growing a second table here.
"""
from sqlalchemy.orm import Session

from models import ActivityLog, User

AUTH_LOGIN = "AUTH_LOGIN"
AUTH_LOGIN_FAILED = "AUTH_LOGIN_FAILED"
AUTH_REGISTER = "AUTH_REGISTER"
DOC_INGEST = "DOC_INGEST"
DOC_DELETE = "DOC_DELETE"
UPLOAD_STORE = "UPLOAD_STORE"
CHAT_TURN = "CHAT_TURN"
SESSION_DELETE = "SESSION_DELETE"
ADMIN_USER_CREATE = "ADMIN_USER_CREATE"
ADMIN_USER_UPDATE = "ADMIN_USER_UPDATE"
ADMIN_USER_DELETE = "ADMIN_USER_DELETE"
ADMIN_LOG_PURGE = "ADMIN_LOG_PURGE"


def record(db: Session, action: str, user: User | None = None, target: str | None = None, **detail) -> None:
    """Add an activity_log row to the caller's unit of work.

    `username` is snapshotted so the row survives the FK nulling out when the
    account is deleted. Anything else goes into `detail` verbatim.
    """
    db.add(
        ActivityLog(
            user_id=user.id if user is not None else None,
            username=user.username if user is not None else None,
            action=action,
            target=target,
            detail=detail,
        )
    )
