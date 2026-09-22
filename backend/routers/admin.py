"""The operator console: what the assistant knows, what has happened, who may use it.

Every route here is behind ADMIN_ONLY, mounted on the router so no endpoint can be
added without it. 403 for a role failure, never 404: an admin surface is not a
secret, an individual session is.

No endpoint reads another user's chat_history. "Lihat semua history" means every
*event* -- see SP2 Decision 3 -- and message text stays owner-scoped exactly as SP0
left it.
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import ActivityLog, ChatHistory, ChatSession, Document, User
from schemas import (
    AdminStats,
    AdminUserCreate,
    AdminUserItem,
    AdminUserPatch,
    ChunkItem,
    KnowledgeItem,
    LogItem,
    LogPurgeResult,
)
from security import hash_password, require_role
from services import audit
from services.upload_service import display_name_of

# One shared callable, not a fresh require_role("ADMIN") per use: FastAPI caches a
# dependency's result per request keyed by the callable itself, so the router guard
# and an endpoint's own `user: User = Depends(ADMIN_ONLY)` are one JWT decode and one
# user lookup rather than two.
ADMIN_ONLY = require_role("ADMIN")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(ADMIN_ONLY)])

CHUNK_PREVIEW_CHARS = 500


def _naive(value: datetime | None) -> datetime | None:
    """created_at is a naive TIMESTAMP holding the server's local time, so an ISO
    string with an offset has to be brought into that frame before it is compared."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


@router.get("/stats", response_model=AdminStats)
def stats(db: Session = Depends(get_db)) -> AdminStats:
    upload_dir = Path(get_settings().upload_dir)
    storage_bytes = sum(p.stat().st_size for p in upload_dir.glob("*") if p.is_file()) if upload_dir.is_dir() else 0

    return AdminStats(
        users=db.query(func.count(User.id)).scalar() or 0,
        active_users=db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0,
        # A document is its filename, so the distinct count is the document count and
        # the row count is the chunk count.
        documents=db.query(func.count(func.distinct(Document.filename))).scalar() or 0,
        chunks=db.query(func.count(Document.id)).scalar() or 0,
        sessions=db.query(func.count(ChatSession.id)).scalar() or 0,
        messages=db.query(func.count(ChatHistory.id)).scalar() or 0,
        storage_bytes=storage_bytes,
    )


@router.get("/documents", response_model=list[KnowledgeItem])
def list_documents(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[KnowledgeItem]:
    """One row per ingested file.

    ponytail: OFFSET pagination, and the ceiling that comes with it -- it degrades
    past ~100k rows. A single-operator corpus will not reach that; switch to keyset
    pagination on (created_at, filename) if it ever does (SP2 Decision 4).
    """
    query = db.query(
        Document.filename,
        func.count(Document.id).label("chunks"),
        func.coalesce(func.sum(func.length(Document.content)), 0).label("chars"),
        func.min(Document.created_at).label("created_at"),
        func.max(Document.user_id).label("user_id"),
    )
    if q:
        query = query.filter(Document.filename.ilike(f"%{q}%"))
    rows = (
        query.group_by(Document.filename)
        .order_by(func.min(Document.created_at).desc(), Document.filename)
        .offset(offset)
        .limit(limit)
        .all()
    )

    # One extra query rather than a GROUP BY join: every chunk of a file carries the
    # same uploader, and the id set is at most `limit` wide.
    owner_ids = {row.user_id for row in rows if row.user_id is not None}
    owners = (
        {u.id: u.username for u in db.query(User).filter(User.id.in_(owner_ids))} if owner_ids else {}
    )

    return [
        KnowledgeItem(
            filename=row.filename,
            display_name=display_name_of(row.filename),
            chunks=row.chunks,
            chars=int(row.chars),
            owner=owners.get(row.user_id),
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/documents/{filename}/chunks", response_model=list[ChunkItem])
def list_chunks(
    filename: str,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[ChunkItem]:
    """The stored text of one file, newest index first in chunk order.

    The path parameter is matched against the column and never joined into a path:
    the file on disk is not opened by this route.
    """
    rows = (
        db.query(Document)
        .filter(Document.filename == filename)
        .order_by(Document.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown document")
    return [
        ChunkItem(
            chunk_index=int(row.doc_metadata.get("chunk_index", 0)),
            chars=len(row.content),
            content=row.content[:CHUNK_PREVIEW_CHARS],
        )
        for row in rows
    ]


@router.delete("/documents/{filename}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    filename: str,
    db: Session = Depends(get_db),
    user: User = Depends(ADMIN_ONLY),
) -> None:
    """Drop every chunk of a file and the stored upload behind it."""
    deleted = db.query(Document).filter(Document.filename == filename).delete(synchronize_session=False)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown document")

    audit.record(db, audit.DOC_DELETE, user=user, target=filename, chunks=deleted)
    # Committed before the file goes, not after: unlinking is irreversible, and doing
    # it inside a unit of work that might still roll back would lose the file while
    # the rows it belonged to came back.
    db.commit()

    upload_dir = Path(get_settings().upload_dir).resolve()
    # Only the final component, and the resolved result must stay inside upload_dir --
    # the same guard _resolve_attachments applies to a client-supplied name.
    candidate = (upload_dir / Path(filename).name).resolve()
    if candidate.is_relative_to(upload_dir):
        candidate.unlink(missing_ok=True)


@router.get("/logs", response_model=list[LogItem])
def list_logs(
    action: str | None = None,
    username: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[ActivityLog]:
    """Newest first. Metadata only -- there is no message text in this table.

    ponytail: OFFSET pagination, with the ceiling that comes with it -- it degrades
    past ~100k rows. The failed-login rows are the only unbounded source; see the
    note in services/audit.py, and DELETE /admin/logs below as the release valve
    (SP2 Decision 4).
    """
    query = db.query(ActivityLog)
    if action:
        query = query.filter(ActivityLog.action == action)
    if username:
        # Both spellings: a failed login has no account row to point at, so the
        # attempted name it carries lives in detail. Filtering on the column alone
        # would hide exactly the rows a security question is about.
        query = query.filter(
            or_(ActivityLog.username == username, ActivityLog.detail["username"].astext == username)
        )
    if since is not None:
        query = query.filter(ActivityLog.created_at >= _naive(since))
    if until is not None:
        query = query.filter(ActivityLog.created_at <= _naive(until))
    return query.order_by(ActivityLog.id.desc()).offset(offset).limit(limit).all()


@router.get("/logs/actions", response_model=list[str])
def list_log_actions(db: Session = Depends(get_db)) -> list[str]:
    """The actions actually present, so the frontend filter is data-driven."""
    rows = db.query(ActivityLog.action).distinct().order_by(ActivityLog.action).all()
    return [row.action for row in rows]


@router.delete("/logs", response_model=LogPurgeResult)
def purge_logs(
    before: datetime,
    db: Session = Depends(get_db),
    user: User = Depends(ADMIN_ONLY),
) -> LogPurgeResult:
    """Retention. `before` is required -- there is no bare "delete the log", and the
    purge's own audit row is written after the cutoff, so it always survives."""
    cutoff = _naive(before)
    deleted = db.query(ActivityLog).filter(ActivityLog.created_at < cutoff).delete(synchronize_session=False)
    audit.record(db, audit.ADMIN_LOG_PURGE, user=user, target=cutoff.isoformat(), deleted=deleted)
    return LogPurgeResult(deleted=deleted)


def _other_active_admins(db: Session, excluding_id: int) -> int:
    return (
        db.query(func.count(User.id))
        .filter(User.role == "ADMIN", User.is_active.is_(True), User.id != excluding_id)
        .scalar()
        or 0
    )


def _user_or_404(db: Session, user_id: int) -> User:
    target = db.query(User).filter_by(id=user_id).one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown user")
    return target


@router.get("/users", response_model=list[AdminUserItem])
def list_users(
    q: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[AdminUserItem]:
    query = db.query(User)
    if q:
        query = query.filter(User.username.ilike(f"%{q}%"))
    users = query.order_by(User.id).offset(offset).limit(limit).all()

    # Two grouped queries rather than a join per row: the counts are per user, and
    # `limit` bounds how many ids can appear.
    ids = [u.id for u in users]
    session_counts = dict(
        db.query(ChatSession.user_id, func.count(ChatSession.id))
        .filter(ChatSession.user_id.in_(ids))
        .group_by(ChatSession.user_id)
        .all()
    )
    # Distinct filenames, the same meaning "documents" carries in /admin/stats.
    document_counts = dict(
        db.query(Document.user_id, func.count(func.distinct(Document.filename)))
        .filter(Document.user_id.in_(ids))
        .group_by(Document.user_id)
        .all()
    )
    return [
        AdminUserItem(
            id=u.id,
            username=u.username,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at,
            sessions=session_counts.get(u.id, 0),
            documents=document_counts.get(u.id, 0),
        )
        for u in users
    ]


@router.post("/users", response_model=AdminUserItem, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(ADMIN_ONLY),
) -> AdminUserItem:
    if db.query(User).filter_by(username=payload.username).one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already exists")
    created = User(username=payload.username, password_hash=hash_password(payload.password), role=payload.role)
    db.add(created)
    db.flush()
    audit.record(db, audit.ADMIN_USER_CREATE, user=user, target=created.username, role=created.role)
    return AdminUserItem(
        id=created.id,
        username=created.username,
        role=created.role,
        is_active=created.is_active,
        created_at=created.created_at,
        sessions=0,
        documents=0,
    )


@router.patch("/users/{user_id}", response_model=AdminUserItem)
def update_user(
    user_id: int,
    payload: AdminUserPatch,
    db: Session = Depends(get_db),
    user: User = Depends(ADMIN_ONLY),
) -> AdminUserItem:
    target = _user_or_404(db, user_id)
    # exclude_none as well as exclude_unset: `role` and `is_active` are declared
    # optional so that omitting them means "leave alone", and an explicit null would
    # otherwise be assigned straight onto a NOT NULL column and 500.
    fields = payload.model_dump(exclude_unset=True, exclude_none=True)

    # Losing admin rights is the irreversible half: demotion, deactivation, deletion.
    # A password change is not, and an admin may change their own.
    loses_admin = (fields.get("role") not in (None, "ADMIN") and target.role == "ADMIN") or (
        fields.get("is_active") is False and target.is_active
    )
    if loses_admin and target.id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="you cannot demote or deactivate yourself")
    if loses_admin and target.role == "ADMIN" and _other_active_admins(db, target.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="the last active admin cannot be demoted or deactivated"
        )

    if "role" in fields:
        target.role = payload.role
    if "is_active" in fields:
        target.is_active = payload.is_active
    if "password" in fields:
        target.password_hash = hash_password(payload.password)
    db.flush()
    # Field names only, never values: the audit log must not become the place a
    # password is written down.
    audit.record(db, audit.ADMIN_USER_UPDATE, user=user, target=target.username, fields=sorted(fields))
    return AdminUserItem(
        id=target.id,
        username=target.username,
        role=target.role,
        is_active=target.is_active,
        created_at=target.created_at,
        sessions=db.query(func.count(ChatSession.id)).filter(ChatSession.user_id == target.id).scalar() or 0,
        documents=db.query(func.count(func.distinct(Document.filename)))
        .filter(Document.user_id == target.id)
        .scalar()
        or 0,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(ADMIN_ONLY),
) -> None:
    """The sharp option, not the normal one: this cascades away the account's
    sessions and chat history, and orphans its documents (SP2 Decision 2).
    Deactivation is what the console offers by default."""
    target = _user_or_404(db, user_id)
    if target.id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="you cannot delete yourself")
    if target.role == "ADMIN" and target.is_active and _other_active_admins(db, target.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="the last active admin cannot be deleted"
        )
    username = target.username
    db.delete(target)
    db.flush()
    audit.record(db, audit.ADMIN_USER_DELETE, user=user, target=username)
