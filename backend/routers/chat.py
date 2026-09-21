import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from agent.orchestrator import AgentError, run_agent, stream_agent
from config import get_settings
from database import SessionLocal, get_db
from models import ChatHistory, User
from schemas import ChatRequest, ChatResponse, HistoryItem, StreamChatRequest
from security import get_current_user, get_or_create_session, require_owned_session
from services.upload_service import UploadRejected, display_name_of, sniff

router = APIRouter(tags=["chat"])

HISTORY_TURNS = 10

TITLE_LIMIT = 60


def _title_from(message: str) -> str:
    """First user message, trimmed to TITLE_LIMIT characters on a word boundary.

    ponytail: truncation, not an LLM-written title. Swap in a one-shot generate
    call if the titles read badly.
    """
    trimmed = message.strip()
    if len(trimmed) <= TITLE_LIMIT:
        return trimmed
    return trimmed[:TITLE_LIMIT].rsplit(" ", 1)[0]


@dataclass
class ResolvedAttachment:
    """An attachment re-derived from the file on disk at chat time."""

    stored_name: str
    display_name: str
    kind: str
    mime: str
    size: int
    path: str

    def ref(self) -> dict:
        return {
            "stored_name": self.stored_name,
            "display_name": self.display_name,
            "kind": self.kind,
            "mime": self.mime,
            "size": self.size,
        }


def _resolve_attachments(names: list[str]) -> list[ResolvedAttachment]:
    """Map client-supplied stored names onto real files inside upload_dir.

    The same per-item guard _resolve_image used, now applied to each name: only
    the final path component is taken, it must stay inside upload_dir and exist.
    Kind and MIME are re-derived from the file -- never from the request.
    """
    upload_dir = Path(get_settings().upload_dir).resolve()
    resolved: list[ResolvedAttachment] = []
    for name in names:
        candidate = (upload_dir / Path(name).name).resolve()
        if not candidate.is_relative_to(upload_dir) or not candidate.is_file():
            raise HTTPException(status_code=400, detail="unknown attachment; upload it first via POST /upload")
        try:
            with candidate.open("rb") as handle:
                kind, mime = sniff(candidate.name, handle.read(64))
        except UploadRejected as exc:
            raise HTTPException(status_code=400, detail=f"stored file no longer matches its name: {exc}") from exc
        resolved.append(
            ResolvedAttachment(
                stored_name=candidate.name,
                display_name=display_name_of(candidate.name),
                kind=kind,
                mime=mime,
                size=candidate.stat().st_size,
                path=str(candidate),
            )
        )
    return resolved


def _prepare_turn(
    db: Session,
    payload: ChatRequest,
    user: User,
    truncate_after_id: int | None = None,
) -> tuple[list[ResolvedAttachment], list[dict], int]:
    """Shared preamble of both chat endpoints: attachment resolution, ownership,
    truncation, the history window, and the user-row insert.

    Returns the resolved attachments, the history window, and the user row's id
    (the streaming endpoint echoes it back so the client can address this turn
    for regenerate/edit). The caller owns the commit. POST /chat lets get_db do
    it after the response; the streaming endpoint must commit before it returns
    the StreamingResponse, because its dependency session is closed by then.
    """
    resolved = _resolve_attachments(payload.attachments)
    session = get_or_create_session(db, payload.session_id, user)
    if session.title is None:  # auto-title from the first message only
        session.title = _title_from(payload.message)

    if truncate_after_id is not None:
        # Scoped by session_id as well as id: an id alone is a cross-session write.
        db.query(ChatHistory).filter(
            ChatHistory.session_id == payload.session_id,
            ChatHistory.id > truncate_after_id,
        ).delete(synchronize_session=False)

    prior = (
        db.query(ChatHistory)
        .filter(ChatHistory.session_id == payload.session_id, ChatHistory.role.in_(("user", "assistant")))
        .order_by(ChatHistory.id.desc())
        .limit(HISTORY_TURNS)
        .all()
    )
    history = [{"role": row.role, "content": row.message} for row in reversed(prior)]

    user_row = ChatHistory(
        session_id=payload.session_id,
        role="user",
        message=payload.message,
        attachments=[r.ref() for r in resolved],
    )
    db.add(user_row)
    db.flush()
    return resolved, history, user_row.id


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    resolved, history, _ = _prepare_turn(db, payload, user)
    image_paths = [r.path for r in resolved if r.kind == "image"]

    try:
        result = run_agent(db=db, message=payload.message, history=history, image_paths=image_paths)
    except AgentError as exc:
        raise HTTPException(status_code=503, detail=f"local LLM unavailable: {exc}") from exc

    db.add(ChatHistory(session_id=payload.session_id, role="assistant", message=result.answer))

    return ChatResponse(answer=result.answer, tool_used=result.tool_used, sources=result.sources)


def _json_default(obj):
    if hasattr(obj, "model_dump"):  # SourceRef and friends ride inside done events
        return obj.model_dump()
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def _sse(event: dict) -> str:
    """One Server-Sent Event frame carrying a stream_agent event verbatim."""
    return f"data: {json.dumps(event, default=_json_default)}\n\n"


@router.post("/chat/stream")
def chat_stream(
    payload: StreamChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    # Capture everything the generator needs now: FastAPI >= 0.106 exits yield
    # dependencies -- get_db among them -- before a StreamingResponse body is
    # sent, so the request's db session is closed by the time the generator runs.
    session_id = payload.session_id
    message = payload.message
    resolved, history, user_row_id = _prepare_turn(db, payload, user, truncate_after_id=payload.truncate_after_id)
    image_paths = [r.path for r in resolved if r.kind == "image"]
    db.commit()  # the pre-stream work is one unit; the generator opens its own session

    def event_source() -> Iterator[str]:
        gen_db = SessionLocal()
        parts: list[str] = []
        persisted = False
        try:
            for event in stream_agent(db=gen_db, message=message, history=history, image_paths=image_paths):
                if event["type"] == "delta":
                    parts.append(event["text"])
                elif event["type"] == "done":
                    # The done answer replaces the joined deltas: it is stripped and
                    # carries any text the JSON-leak guard held back.
                    parts[:] = [event["answer"]]
                    persisted = True
                    assistant_row = ChatHistory(session_id=session_id, role="assistant", message=event["answer"])
                    gen_db.add(assistant_row)
                    gen_db.commit()  # expire_on_commit=False keeps the assigned id
                    # The client addresses this turn by row id for regenerate/edit.
                    event = {**event, "user_row_id": user_row_id, "assistant_row_id": assistant_row.id}
                yield _sse(event)
        except AgentError as exc:
            # The response has already started, so this can no longer be a 503.
            yield _sse({"type": "error", "detail": f"local LLM unavailable: {exc}"})
        finally:
            if not persisted and parts:
                # Stop pressed or the model died mid-answer: a stopped answer that
                # vanishes on reload is worse than a truncated one that stays.
                gen_db.add(ChatHistory(session_id=session_id, role="assistant", message="".join(parts)))
                gen_db.commit()
            gen_db.close()

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/chat/history", response_model=list[HistoryItem])
def history(
    session_id: str = Query(min_length=1, max_length=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatHistory]:
    require_owned_session(db, session_id, user)
    return (
        db.query(ChatHistory)
        .filter_by(session_id=session_id)
        .order_by(ChatHistory.id)
        .all()
    )
