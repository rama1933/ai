"""POST /chat/stream: SSE framing, persistence, truncation, ownership."""
import base64
import json
import uuid

import pytest

from agent.orchestrator import AgentError, AgentResult
from database import SessionLocal
from models import ChatHistory, ChatSession, User
from schemas import SourceRef


def _sse_events(body: str) -> list[dict]:
    """Parse an SSE body into the event dicts its data: frames carry."""
    return [json.loads(frame[len("data: "):]) for frame in body.split("\n\n") if frame.startswith("data: ")]


def _username_of(headers: dict[str, str]) -> str:
    payload = headers["Authorization"].split(" ", 1)[1].split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["sub"]


@pytest.fixture
def auth_headers(client) -> dict[str, str]:
    username = f"stream-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": "supersecret1"})
    token = client.post("/auth/login", json={"username": username, "password": "supersecret1"}).json()["access_token"]
    yield {"Authorization": f"Bearer {token}"}
    session = SessionLocal()
    session.query(User).filter_by(username=username).delete(synchronize_session=False)
    session.commit()
    session.close()


@pytest.fixture
def session_id() -> str:
    sid = f"stream-{uuid.uuid4().hex[:8]}"
    yield sid
    session = SessionLocal()
    session.query(ChatSession).filter_by(id=sid).delete(synchronize_session=False)
    session.commit()
    session.close()


def _patch_stream(monkeypatch, events: list[dict]) -> None:
    """Replace the agent generator with one that emits the given events."""
    from routers import chat as chat_router

    def fake(db, message, history, image_paths):
        yield from events

    monkeypatch.setattr(chat_router, "stream_agent", fake)


def test_stream_yields_deltas_then_exactly_one_done(client, auth_headers, session_id, monkeypatch):
    _patch_stream(
        monkeypatch,
        [
            {"type": "delta", "text": "Halo"},
            {"type": "delta", "text": ", apa lagi?"},
            {"type": "done", "answer": "Halo, apa lagi?", "tool_used": None, "sources": []},
        ],
    )

    response = client.post("/chat/stream", headers=auth_headers, json={"session_id": session_id, "message": "halo"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response.text)
    assert [e["type"] for e in events] == ["delta", "delta", "done"]
    assert events[-1]["answer"] == "Halo, apa lagi?"


def test_stream_emits_tool_and_sources_before_the_first_delta(client, auth_headers, session_id, monkeypatch):
    _patch_stream(
        monkeypatch,
        [
            {"type": "tool", "name": "rag_search"},
            {"type": "sources", "sources": [SourceRef(filename="policy.pdf", score=0.9)]},
            {"type": "delta", "text": "5 tahun."},
            {
                "type": "done",
                "answer": "5 tahun.",
                "tool_used": "rag_search",
                "sources": [SourceRef(filename="policy.pdf", score=0.9)],
            },
        ],
    )

    response = client.post(
        "/chat/stream", headers=auth_headers, json={"session_id": session_id, "message": "berapa retensi?"}
    )

    events = _sse_events(response.text)
    assert [e["type"] for e in events] == ["tool", "sources", "delta", "done"]
    assert events[0]["name"] == "rag_search"
    assert events[1]["sources"][0]["filename"] == "policy.pdf"  # SourceRef survived serialisation


def test_stream_agent_error_emits_error_event_and_no_done(client, auth_headers, session_id, monkeypatch):
    from routers import chat as chat_router

    def failing(db, message, history, image_paths):
        yield {"type": "delta", "text": "sebagian"}
        raise AgentError("cannot reach Ollama: connection refused")

    monkeypatch.setattr(chat_router, "stream_agent", failing)

    response = client.post("/chat/stream", headers=auth_headers, json={"session_id": session_id, "message": "halo"})

    events = _sse_events(response.text)
    assert [e["type"] for e in events] == ["delta", "error"]
    assert "local LLM unavailable" in events[-1]["detail"]


def test_stream_persists_user_and_assistant_rows_after_the_stream_closes(
    client, auth_headers, session_id, monkeypatch
):
    """The DB-session trap regression guard: the generator runs after get_db has
    exited, so it must persist on its own session -- or the assistant row never
    lands."""
    _patch_stream(
        monkeypatch,
        [
            {"type": "delta", "text": "Halo"},
            {"type": "done", "answer": "Halo.", "tool_used": None, "sources": []},
        ],
    )

    client.post("/chat/stream", headers=auth_headers, json={"session_id": session_id, "message": "halo"})

    session = SessionLocal()
    rows = session.query(ChatHistory).filter_by(session_id=session_id).order_by(ChatHistory.id).all()
    session.close()
    assert [(r.role, r.message) for r in rows] == [("user", "halo"), ("assistant", "Halo.")]


def test_stream_truncate_after_id_deletes_only_that_sessions_trailing_rows(client, auth_headers, monkeypatch):
    """Two sessions for the caller; the survivor's rows have HIGHER ids than the
    truncation point, so an id-only delete would destroy them."""
    _patch_stream(
        monkeypatch,
        [{"type": "done", "answer": "Jawaban baru.", "tool_used": None, "sources": []}],
    )
    setup = SessionLocal()
    owner = setup.query(User).filter_by(username=_username_of(auth_headers)).one()
    cut_sid = f"stream-{uuid.uuid4().hex[:8]}"
    keep_sid = f"stream-{uuid.uuid4().hex[:8]}"
    setup.add(ChatSession(id=cut_sid, user_id=owner.id))
    setup.add(ChatSession(id=keep_sid, user_id=owner.id))
    setup.flush()
    setup.add(ChatHistory(session_id=cut_sid, role="user", message="cut-1"))
    setup.add(ChatHistory(session_id=cut_sid, role="assistant", message="cut-2"))
    setup.add(ChatHistory(session_id=cut_sid, role="user", message="cut-3"))
    setup.flush()
    truncate_at = setup.query(ChatHistory).filter_by(session_id=cut_sid, message="cut-2").one().id
    setup.add(ChatHistory(session_id=keep_sid, role="user", message="keep-1"))
    setup.commit()
    setup.close()

    response = client.post(
        "/chat/stream",
        headers=auth_headers,
        json={"session_id": cut_sid, "message": "tanya ulang", "truncate_after_id": truncate_at},
    )

    assert response.status_code == 200
    session = SessionLocal()
    cut = [r.message for r in session.query(ChatHistory).filter_by(session_id=cut_sid).order_by(ChatHistory.id)]
    keep = [r.message for r in session.query(ChatHistory).filter_by(session_id=keep_sid).order_by(ChatHistory.id)]
    session.close()
    assert cut == ["cut-1", "cut-2", "tanya ulang", "Jawaban baru."]
    assert keep == ["keep-1"], "another session's rows after the id must survive"


def test_stream_answers_404_for_another_users_session(client, auth_headers, monkeypatch):
    """404 before any byte: no event frames, and no confirmation the session exists."""
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router,
        "run_agent",
        lambda db, message, history, image_paths: AgentResult(answer="ok", tool_used=None, sources=[]),
    )
    username_b = f"stream-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username_b, "password": "supersecret1"})
    token_b = client.post("/auth/login", json={"username": username_b, "password": "supersecret1"}).json()[
        "access_token"
    ]
    sid = f"stream-{uuid.uuid4().hex[:8]}"
    client.post(
        "/chat", headers={"Authorization": f"Bearer {token_b}"}, json={"session_id": sid, "message": "rahasia B"}
    )

    response = client.post("/chat/stream", headers=auth_headers, json={"session_id": sid, "message": "halo"})

    assert response.status_code == 404
    assert "rahasia B" not in response.text
    assert not _sse_events(response.text)
    session = SessionLocal()
    session.query(User).filter_by(username=username_b).delete(synchronize_session=False)
    session.commit()
    session.close()
