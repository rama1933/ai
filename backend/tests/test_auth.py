import uuid

import pytest

from database import SessionLocal
from models import User


@pytest.fixture
def fresh_username() -> str:
    return f"auth-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup_users():
    """Delete only the users THIS module created.

    A broad 'user-%' pattern also matches the end-to-end matrix's 'user-<hex8>'
    accounts, so a concurrent pytest process would delete the matrix's user
    mid-run and collapse it with 401 "unknown user".
    """
    yield
    session = SessionLocal()
    session.query(User).filter(User.username.like("auth-user-%")).delete(synchronize_session=False)
    session.commit()
    session.close()


def test_register_then_login_returns_token(client, fresh_username):
    register = client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    assert register.status_code == 201

    login = client.post("/auth/login", json={"username": fresh_username, "password": "supersecret1"})
    assert login.status_code == 200
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "USER"
    assert len(body["access_token"]) > 20


def test_login_with_wrong_password_is_401(client, fresh_username):
    client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    response = client.post("/auth/login", json={"username": fresh_username, "password": "wrongpassword"})
    assert response.status_code == 401


def test_register_rejects_duplicate_username(client, fresh_username):
    client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    duplicate = client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    assert duplicate.status_code == 409


def test_password_is_not_stored_in_plain_text(client, fresh_username):
    client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    session = SessionLocal()
    stored = session.query(User).filter_by(username=fresh_username).one()
    session.close()
    assert stored.password_hash != "supersecret1"
    assert stored.password_hash.startswith("$2")


def test_protected_route_requires_token(client):
    assert client.get("/chat/history?session_id=x").status_code == 401


def test_deactivated_user_is_locked_out_at_once(client, fresh_username):
    """Both paths, because only one of them goes through get_current_user.

    A stale token is the case deactivation exists for: the UI can hold a valid JWT
    for another hour, and it must stop working the moment the account is turned off.
    """
    client.post("/auth/register", json={"username": fresh_username, "password": "supersecret1"})
    token = client.post("/auth/login", json={"username": fresh_username, "password": "supersecret1"}).json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}

    session = SessionLocal()
    session.query(User).filter_by(username=fresh_username).update({"is_active": False})
    session.commit()
    session.close()

    assert client.get("/auth/me", headers=headers).status_code == 401
    assert client.get("/sessions", headers=headers).status_code == 401
    relogin = client.post("/auth/login", json={"username": fresh_username, "password": "supersecret1"})
    assert relogin.status_code == 401
