import uuid

import pytest

from database import SessionLocal
from models import User


@pytest.fixture
def fresh_username() -> str:
    return f"user-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup_users():
    yield
    session = SessionLocal()
    session.query(User).filter(User.username.like("user-%")).delete(synchronize_session=False)
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


@pytest.mark.xfail(reason="route added in Task 13", strict=False)
def test_protected_route_requires_token(client):
    assert client.get("/chat/history?session_id=x").status_code == 401
