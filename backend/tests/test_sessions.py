"""Session CRUD: GET/POST /sessions, PATCH/DELETE /sessions/{id}, auto-title."""
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from database import SessionLocal
from models import ChatHistory, ChatSession, User


def _username_of(headers: dict[str, str]) -> str:
    payload = headers["Authorization"].split(" ", 1)[1].split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["sub"]


@pytest.fixture
def auth_headers(client) -> dict[str, str]:
    username = f"sessions-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": "supersecret1"})
    token = client.post("/auth/login", json={"username": username, "password": "supersecret1"}).json()["access_token"]
    yield {"Authorization": f"Bearer {token}"}
    session = SessionLocal()
    session.query(User).filter(User.username.like("sessions-%")).delete(synchronize_session=False)
    session.commit()
    session.close()


@pytest.fixture
def second_user_headers(client) -> dict[str, str]:
    username = f"sessions-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": "supersecret1"})
    token = client.post("/auth/login", json={"username": username, "password": "supersecret1"}).json()["access_token"]
    yield {"Authorization": f"Bearer {token}"}


@pytest.fixture
def quiet_agent(monkeypatch):
    from agent.orchestrator import AgentResult
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router,
        "run_agent",
        lambda db, message, history, image_paths, document_filenames=None: AgentResult(answer="ok", tool_used=None, sources=[]),
    )


def _seed_session(username: str, sid: str, *, title: str | None, updated_at: datetime, messages: list[str]):
    """Insert a session owned by username with the given history, directly."""
    session = SessionLocal()
    user = session.query(User).filter_by(username=username).one()
    row = ChatSession(id=sid, user_id=user.id, title=title, updated_at=updated_at)
    session.add(row)
    session.flush()
    for i, message in enumerate(messages):
        session.add(ChatHistory(session_id=sid, role="user" if i % 2 == 0 else "assistant", message=message))
    session.commit()
    session.close()


def test_list_returns_only_callers_rows_newest_first(client, auth_headers):
    username = _username_of(auth_headers)
    base = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
    mine = [f"sessions-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    for i, sid in enumerate(mine):
        _seed_session(username, sid, title=f"S{i}", updated_at=base + timedelta(minutes=i), messages=[])
    foreign_headers = _make_second(client)
    _seed_session(
        _username_of(foreign_headers),
        f"sessions-{uuid.uuid4().hex[:8]}",
        title="foreign",
        updated_at=base + timedelta(hours=1),
        messages=[],
    )

    response = client.get("/sessions", headers=auth_headers)

    assert response.status_code == 200
    listed = [s["id"] for s in response.json()]
    assert listed == list(reversed(mine))  # updated_at DESC


def _make_second(client) -> dict[str, str]:
    """A second account whose rows must never leak into another user's list."""
    username = f"sessions-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": "supersecret1"})
    token = client.post("/auth/login", json={"username": username, "password": "supersecret1"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_returns_server_generated_id_history_accepts(client, auth_headers):
    response = client.post("/sessions", headers=auth_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("session-")
    assert body["title"] is None

    history = client.get(f"/chat/history?session_id={body['id']}", headers=auth_headers)
    assert history.status_code == 200
    assert history.json() == []


def test_rename_persists(client, auth_headers):
    sid = f"sessions-{uuid.uuid4().hex[:8]}"
    _seed_session(_username_of(auth_headers), sid, title=None, updated_at=datetime.now(timezone.utc), messages=["halo"])

    renamed = client.patch(f"/sessions/{sid}", headers=auth_headers, json={"title": "Retensi dokumen"})
    fetched = next(s for s in client.get("/sessions", headers=auth_headers).json() if s["id"] == sid)

    assert renamed.status_code == 200
    assert fetched["title"] == "Retensi dokumen"


def test_delete_cascades_chat_history_to_zero_rows(client, auth_headers):
    username = _username_of(auth_headers)
    sid = f"sessions-{uuid.uuid4().hex[:8]}"
    _seed_session(
        username, sid, title="t", updated_at=datetime.now(timezone.utc), messages=["satu", "dua", "tiga"]
    )

    response = client.delete(f"/sessions/{sid}", headers=auth_headers)

    assert response.status_code == 204
    session = SessionLocal()
    assert session.query(ChatSession).filter_by(id=sid).one_or_none() is None
    assert session.query(ChatHistory).filter_by(session_id=sid).count() == 0
    session.close()


def test_foreign_session_is_404_not_403_on_patch_delete_and_history(client, auth_headers, second_user_headers):
    """Every ownership failure stays 404: a 403 would confirm the session exists."""
    sid = f"sessions-{uuid.uuid4().hex[:8]}"
    _seed_session(
        _username_of(auth_headers),
        sid,
        title="rahasia",
        updated_at=datetime.now(timezone.utc),
        messages=["rahasia A"],
    )

    patch = client.patch(f"/sessions/{sid}", headers=second_user_headers, json={"title": "milik B"})
    delete = client.delete(f"/sessions/{sid}", headers=second_user_headers)
    history = client.get(f"/chat/history?session_id={sid}", headers=second_user_headers)

    assert patch.status_code == 404
    assert delete.status_code == 404
    assert history.status_code == 404
    assert "rahasia" not in history.text


def test_first_message_autotitles_trimmed_on_a_word_boundary(client, auth_headers, quiet_agent):
    long_message = "ini adalah pertanyaan yang sangat panjang sekali mengenai kebijakan retensi dokumen perusahaan"
    assert len(long_message.strip()) > 60

    response = client.post(
        "/chat",
        headers=auth_headers,
        json={"session_id": f"sessions-{uuid.uuid4().hex[:8]}", "message": long_message},
    )
    assert response.status_code == 200

    listed = client.get("/sessions", headers=auth_headers).json()
    title = listed[0]["title"]
    assert len(title) <= 60
    assert title.startswith("ini adalah pertanyaan")
    assert long_message.startswith(title), "cut on a word boundary, mid-word"


def test_autotitle_never_overwrites_a_renamed_session(client, auth_headers, quiet_agent):
    sid = f"sessions-{uuid.uuid4().hex[:8]}"
    _seed_session(
        _username_of(auth_headers), sid, title="Judul pilihan user",
        updated_at=datetime.now(timezone.utc), messages=["halo"],
    )

    client.post("/chat", headers=auth_headers, json={"session_id": sid, "message": "pesan baru yang berbeda"})

    listed = client.get("/sessions", headers=auth_headers).json()
    assert next(s for s in listed if s["id"] == sid)["title"] == "Judul pilihan user"
