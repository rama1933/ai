from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import ChatSession, User

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)

ROLES = ("ADMIN", "USER", "READ_ONLY")


def hash_password(raw: str) -> str:
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd.verify(raw, hashed)


def create_access_token(username: str, role: str) -> str:
    settings = get_settings()
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    settings = get_settings()
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc

    user = db.query(User).filter_by(username=payload.get("sub")).one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown user")
    # The row is already fetched on every request, so deactivation bites on the next
    # call rather than whenever the token happens to expire.
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account disabled")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"requires role in {roles}")
        return user

    return dependency


def require_owned_session(db: Session, session_id: str, user: User) -> ChatSession:
    """Return the caller's session.

    404 rather than 403 on both branches, deliberately: a 403 would confirm that the
    session exists, which is exactly the fact an attacker wants. "No such session" and
    "not yours" must be indistinguishable.
    """
    session = db.query(ChatSession).filter_by(id=session_id).one_or_none()
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown session")
    return session


def get_or_create_session(db: Session, session_id: str, user: User) -> ChatSession:
    """Return the caller's session, creating it on the first message.

    The explicit flush is load-bearing, not stylistic. `chat()` adds the ChatHistory
    row and calls a single `db.flush()`, so both INSERTs are pending in one unit of
    work. SQLAlchemy orders pending INSERTs by `Mapper._sort_key` -- module.ClassName --
    because these models declare no relationship() to give it a dependency edge, and
    `models.ChatHistory` sorts before `models.ChatSession`. Without the flush the
    chat_history INSERT goes first and the foreign key rejects it.

    `updated_at` is assigned a real `datetime`, not `func.now()`. A SQL construct
    assigned to a mapped attribute stays a construct in the identity map until the
    next flush, and `get_db` commits only after the endpoint returns -- so an
    endpoint that serialised this object would hand Pydantic a `Function` and fail
    validation. `datetime.now(timezone.utc)` stores the same instant the column's
    `CURRENT_TIMESTAMP` default would: the column is a naive TIMESTAMP, so
    Postgres renders the bound timestamptz in the session's time zone.
    """
    session = db.query(ChatSession).filter_by(id=session_id).one_or_none()
    if session is None:
        session = ChatSession(id=session_id, user_id=user.id)
        db.add(session)
        db.flush()
    elif session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown session")
    session.updated_at = datetime.now(timezone.utc)
    return session
