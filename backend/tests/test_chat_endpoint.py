import uuid

import pytest

from agent.orchestrator import AgentResult
from database import SessionLocal
from models import ChatHistory, ChatSession, User
from schemas import SourceRef


@pytest.fixture
def auth_headers(client) -> dict[str, str]:
    username = f"user-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": "supersecret1"})
    token = client.post("/auth/login", json={"username": username, "password": "supersecret1"}).json()["access_token"]
    yield {"Authorization": f"Bearer {token}"}
    session = SessionLocal()
    session.query(User).filter_by(username=username).delete(synchronize_session=False)
    session.commit()
    session.close()


@pytest.fixture
def session_id() -> str:
    sid = f"test-{uuid.uuid4().hex[:8]}"
    yield sid
    session = SessionLocal()
    session.query(ChatSession).filter_by(id=sid).delete(synchronize_session=False)
    session.commit()
    session.close()


def test_chat_requires_authentication(client, session_id):
    response = client.post("/chat", json={"session_id": session_id, "message": "halo"})
    assert response.status_code == 401


def test_chat_returns_answer_tool_and_sources(client, auth_headers, session_id, monkeypatch):
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router, "run_agent",
        lambda db, message, history, image_paths, document_filenames=None: AgentResult(
            answer="Masa retensi 5 tahun.",
            tool_used="rag_search",
            sources=[SourceRef(filename="policy.pdf", score=0.9)],
        ),
    )

    response = client.post(
        "/chat", headers=auth_headers, json={"session_id": session_id, "message": "berapa lama retensi?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Masa retensi 5 tahun."
    assert body["tool_used"] == "rag_search"
    assert body["sources"][0]["filename"] == "policy.pdf"


def test_chat_persists_user_and_assistant_turns(client, auth_headers, session_id, monkeypatch):
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router, "run_agent",
        lambda db, message, history, image_paths, document_filenames=None: AgentResult(answer="hai", tool_used=None, sources=[]),
    )
    client.post("/chat", headers=auth_headers, json={"session_id": session_id, "message": "halo"})

    session = SessionLocal()
    rows = session.query(ChatHistory).filter_by(session_id=session_id).order_by(ChatHistory.id).all()
    session.close()
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].message == "halo"
    assert rows[1].message == "hai"


def test_chat_passes_prior_history_to_the_agent(client, auth_headers, session_id, monkeypatch):
    from routers import chat as chat_router

    captured = {}

    def fake_agent(db, message, history, image_paths, document_filenames=None):
        captured["history"] = history
        return AgentResult(answer="ok", tool_used=None, sources=[])

    monkeypatch.setattr(chat_router, "run_agent", fake_agent)

    client.post("/chat", headers=auth_headers, json={"session_id": session_id, "message": "pertama"})
    client.post("/chat", headers=auth_headers, json={"session_id": session_id, "message": "kedua"})

    assert captured["history"] == [{"role": "user", "content": "pertama"}, {"role": "assistant", "content": "ok"}]


def test_chat_returns_503_when_ollama_is_unreachable(client, auth_headers, session_id, monkeypatch):
    """A dead local LLM is an availability problem, so it must be 503, not 500.

    Regression: _chat() called httpx.post with no try/except, so a refused
    connection escaped as an unhandled httpx.ConnectError and FastAPI answered
    500 Internal Server Error. Task 20 Step 2 requires 503.
    """
    import httpx

    from agent import orchestrator

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    # The agent loop streams over httpx.stream since the SP1 generator refactor.
    monkeypatch.setattr(orchestrator.httpx, "stream", refuse)

    response = client.post("/chat", headers=auth_headers, json={"session_id": session_id, "message": "halo"})

    assert response.status_code == 503
    assert "local LLM unavailable" in response.json()["detail"]


def test_document_ingest_returns_503_when_embedding_model_is_unreachable(client, auth_headers, monkeypatch, tmp_path):
    """Same contract on the ingest path: embedding model down is 503, not 500."""
    import httpx

    from services import embedding_service

    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(embedding_service.httpx, "post", refuse)

    policy = tmp_path / "policy.txt"
    policy.write_text("kebijakan cuti tahunan 12 hari", encoding="utf-8")

    with policy.open("rb") as handle:
        response = client.post("/documents", headers=auth_headers, files={"file": ("policy.txt", handle, "text/plain")})

    assert response.status_code == 503
    assert "embedding model unavailable" in response.json()["detail"]


def test_history_endpoint_returns_turns_in_order(client, auth_headers, session_id, monkeypatch):
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router, "run_agent",
        lambda db, message, history, image_paths, document_filenames=None: AgentResult(answer="jawab", tool_used=None, sources=[]),
    )
    client.post("/chat", headers=auth_headers, json={"session_id": session_id, "message": "tanya"})

    response = client.get(f"/chat/history?session_id={session_id}", headers=auth_headers)

    assert response.status_code == 200
    items = response.json()
    assert [i["role"] for i in items] == ["user", "assistant"]
