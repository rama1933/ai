from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import ChatHistory, ChatSession, User
from security import get_current_user

router = APIRouter(tags=["attachments"])


@router.get("/attachments/{stored_name}")
def get_attachment(
    stored_name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """Serve an attachment to someone whose conversation references it.

    An upload that was never sent is unreachable by design -- the composer
    previews straight from the local File, so there is no round trip to protect.
    Every failure is 404, never 403: confirming existence is the leak.
    """
    upload_dir = Path(get_settings().upload_dir).resolve()
    candidate = (upload_dir / Path(stored_name).name).resolve()
    safe_name = candidate.name
    if not candidate.is_relative_to(upload_dir) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="unknown attachment")

    # A plain <img src> cannot carry the bearer token, so the frontend fetches
    # with it and hands the browser an object URL; this route is that guard.
    row = (
        db.query(ChatHistory.attachments)
        .join(ChatSession, ChatHistory.session_id == ChatSession.id)
        .filter(
            ChatSession.user_id == user.id,
            ChatHistory.attachments.contains([{"stored_name": safe_name}]),
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="unknown attachment")
    ref = next((a for a in row[0] if isinstance(a, dict) and a.get("stored_name") == safe_name), None)
    if ref is None:
        raise HTTPException(status_code=404, detail="unknown attachment")

    return FileResponse(
        path=candidate,
        media_type=ref.get("mime") or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{ref.get("display_name", safe_name)}"'},
    )
