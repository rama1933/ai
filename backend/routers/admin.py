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
from schemas import AdminStats, ChunkItem, KnowledgeItem, LogItem, LogPurgeResult
from security import require_role
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

    upload_dir = Path(get_settings().upload_dir).resolve()
    # Only the final component, and the resolved result must stay inside upload_dir --
    # the same guard _resolve_attachments applies to a client-supplied name.
    candidate = (upload_dir / Path(filename).name).resolve()
    if candidate.is_relative_to(upload_dir):
        candidate.unlink(missing_ok=True)

    audit.record(db, audit.DOC_DELETE, user=user, target=filename, chunks=deleted)


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
