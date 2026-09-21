from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agent.orchestrator import AgentError, run_agent
from config import get_settings
from database import get_db
from models import ChatHistory, User
from schemas import ChatRequest, ChatResponse, HistoryItem
from security import get_current_user

router = APIRouter(tags=["chat"])

HISTORY_TURNS = 10


def _resolve_image(image_name: str | None) -> str | None:
    """Map the client-supplied upload name onto a real path inside upload_dir."""
    if not image_name:
        return None
    upload_dir = Path(get_settings().upload_dir).resolve()
    candidate = (upload_dir / Path(image_name).name).resolve()
    if not candidate.is_relative_to(upload_dir) or not candidate.is_file():
        raise HTTPException(status_code=400, detail="unknown image; upload it first via POST /upload")
    return str(candidate)


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    image_path = _resolve_image(payload.image_path)

    prior = (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == payload.session_id, ChatHistory.role.in_(("user", "assistant")))
        .order_by(ChatHistory.id.desc())
        .limit(HISTORY_TURNS)
        .all()
    )
    history = [{"role": row.role, "content": row.message} for row in reversed(prior)]

    db.add(ChatHistory(session_id=payload.session_id, role="user", message=payload.message))
    db.flush()

    try:
        result = run_agent(db=db, message=payload.message, history=history, image_path=image_path)
    except AgentError as exc:
        raise HTTPException(status_code=503, detail=f"local LLM unavailable: {exc}") from exc

    db.add(ChatHistory(session_id=payload.session_id, role="assistant", message=result.answer))

    return ChatResponse(answer=result.answer, tool_used=result.tool_used, sources=result.sources)


@router.get("/chat/history", response_model=list[HistoryItem])
def history(
    session_id: str = Query(min_length=1, max_length=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatHistory]:
    return (
        db.query(ChatHistory)
        .filter_by(session_id=session_id)
        .order_by(ChatHistory.id)
        .all()
    )
