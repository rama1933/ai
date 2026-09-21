import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import ChatSession, User
from schemas import SessionPatch, SessionSummary
from security import get_current_user, require_owned_session

router = APIRouter(tags=["sessions"])

# A sidebar stops being the right surface well before 200 conversations, so no
# pagination. sessions_user_idx covers exactly this query.
SESSIONS_LIMIT = 200


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatSession]:
    """The caller's conversations, newest activity first."""
    return (
        db.query(ChatSession)
        .filter(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(SESSIONS_LIMIT)
        .all()
    )


@router.post("/sessions", response_model=SessionSummary, status_code=201)
def create_session(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatSession:
    """An empty conversation with a server-generated id: the client stops inventing ids."""
    session = ChatSession(id=f"session-{uuid.uuid4()}", user_id=user.id)
    db.add(session)
    db.flush()
    return session


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
def rename_session(
    session_id: str,
    patch: SessionPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatSession:
    session = require_owned_session(db, session_id, user)
    session.title = patch.title
    db.flush()
    return session


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    # chat_history follows through the FK's ON DELETE CASCADE; the models declare
    # no relationship(), so the database does the cascading, not the ORM.
    session = require_owned_session(db, session_id, user)
    db.delete(session)
    db.flush()
