import uuid

import pytest

from agent.orchestrator import AgentResult
from database import SessionLocal
from models import ChatHistory, User
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
    session.query(ChatHistory).filter_by(session_id=sid).delete(synchronize_session=False)
    session.commit()
    session.close()


def test_chat_requires_authentication(client, session_id):
    response = client.post("/chat", json={"session_id": session_id, "message": "halo"})
    assert response.status_code == 401


def test_chat_returns_answer_tool_and_sources(client, auth_headers, session_id, monkeypatch):
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router, "run_agent",
        lambda db, message, history, image_path: AgentResult(
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
        lambda db, message, history, image_path: AgentResult(answer="hai", tool_used=None, sources=[]),
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

    def fake_agent(db, message, history, image_path):
        captured["history"] = history
        return AgentResult(answer="ok", tool_used=None, sources=[])

    monkeypatch.setattr(chat_router, "run_agent", fake_agent)

    client.post("/chat", headers=auth_headers, json={"session_id": session_id, "message": "pertama"})
    client.post("/chat", headers=auth_headers, json={"session_id": session_id, "message": "kedua"})

    assert captured["history"] == [{"role": "user", "content": "pertama"}, {"role": "assistant", "content": "ok"}]


def test_history_endpoint_returns_turns_in_order(client, auth_headers, session_id, monkeypatch):
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router, "run_agent",
        lambda db, message, history, image_path: AgentResult(answer="jawab", tool_used=None, sources=[]),
    )
    client.post("/chat", headers=auth_headers, json={"session_id": session_id, "message": "tanya"})

    response = client.get(f"/chat/history?session_id={session_id}", headers=auth_headers)

    assert response.status_code == 200
    items = response.json()
    assert [i["role"] for i in items] == ["user", "assistant"]
