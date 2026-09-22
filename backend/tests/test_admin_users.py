"""SP2 Task 6: user management, its three guards, and the audit rows they leave."""
import uuid

import pytest

from database import SessionLocal
from models import ActivityLog, User

PASSWORD = "supersecret1"


def _register(client, username: str) -> None:
    client.post("/auth/register", json={"username": username, "password": PASSWORD})


def _login(client, username: str) -> dict[str, str]:
    token = client.post("/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(client) -> tuple[dict, str]:
    """(headers, username) for a promoted admin. Promotion is by hand: no endpoint
    mints one (SP2 Decision 6), so the test does what the README tells a human to do."""
    username = f"adm-{uuid.uuid4().hex[:8]}"
    _register(client, username)
    session = SessionLocal()
    session.query(User).filter_by(username=username).update({"role": "ADMIN"})
    session.commit()
    session.close()
    return _login(client, username), username


@pytest.fixture
def plain_user(client) -> dict[str, str]:
    username = f"usr-{uuid.uuid4().hex[:8]}"
    _register(client, username)
    return _login(client, username)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    session = SessionLocal()
    session.query(ActivityLog).filter(ActivityLog.username.like("adm-%")).delete(synchronize_session=False)
    for prefix in ("adm-%", "usr-%", "target-%"):
        session.query(User).filter(User.username.like(prefix)).delete(synchronize_session=False)
    session.commit()
    session.close()


@pytest.fixture
def solo_admin(client, admin):
    """An admin who is the only *active* one, which is the state the last-admin
    invariant is about. The others are put back even when the test fails."""
    headers, username = admin
    session = SessionLocal()
    others = [
        row.id
        for row in session.query(User)
        .filter(User.role == "ADMIN", User.is_active.is_(True), User.username != username)
        .all()
    ]
    session.query(User).filter(User.id.in_(others)).update({"is_active": False}, synchronize_session=False)
    session.commit()
    session.close()
    try:
        yield headers, username
    finally:
        session = SessionLocal()
        session.query(User).filter(User.id.in_(others)).update({"is_active": True}, synchronize_session=False)
        session.commit()
        session.close()


def _active_admins() -> int:
    session = SessionLocal()
    count = session.query(User).filter(User.role == "ADMIN", User.is_active.is_(True)).count()
    session.close()
    return count


def test_user_role_is_forbidden_on_the_user_routes(client, plain_user):
    assert client.get("/admin/users", headers=plain_user).status_code == 403
    assert client.post(
        "/admin/users", headers=plain_user, json={"username": "x", "password": PASSWORD}
    ).status_code == 403
    assert client.patch("/admin/users/1", headers=plain_user, json={"role": "ADMIN"}).status_code == 403
    assert client.delete("/admin/users/1", headers=plain_user).status_code == 403


def test_created_user_can_log_in_and_the_creation_is_audited(client, admin):
    headers, _ = admin
    username = f"target-{uuid.uuid4().hex[:8]}"

    created = client.post(
        "/admin/users", headers=headers, json={"username": username, "password": PASSWORD, "role": "READ_ONLY"}
    )

    assert created.status_code == 201, created.text
    assert created.json()["role"] == "READ_ONLY"
    assert created.json()["is_active"] is True
    assert _login(client, username)  # the account is real
    session = SessionLocal()
    row = session.query(ActivityLog).filter_by(action="ADMIN_USER_CREATE", target=username).one()
    session.close()
    assert row.detail == {"role": "READ_ONLY"}
    assert client.post(
        "/admin/users", headers=headers, json={"username": username, "password": PASSWORD}
    ).status_code == 409


def test_deactivating_a_user_kills_their_existing_token(client, admin):
    """End-to-end form of Task 3: the point of deactivation is that it does not wait
    for the JWT to expire."""
    headers, _ = admin
    username = f"target-{uuid.uuid4().hex[:8]}"
    client.post("/admin/users", headers=headers, json={"username": username, "password": PASSWORD})
    victim = _login(client, username)
    assert client.get("/sessions", headers=victim).status_code == 200
    user_id = client.get("/admin/users", headers=headers, params={"q": username}).json()[0]["id"]

    patched = client.patch(f"/admin/users/{user_id}", headers=headers, json={"is_active": False})

    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    assert client.get("/sessions", headers=victim).status_code == 401


def test_a_password_change_is_audited_by_field_name_only(client, admin):
    headers, _ = admin
    username = f"target-{uuid.uuid4().hex[:8]}"
    client.post("/admin/users", headers=headers, json={"username": username, "password": PASSWORD})
    user_id = client.get("/admin/users", headers=headers, params={"q": username}).json()[0]["id"]

    response = client.patch(f"/admin/users/{user_id}", headers=headers, json={"password": "brandnewpass1"})

    assert response.status_code == 200
    session = SessionLocal()
    row = (
        session.query(ActivityLog)
        .filter_by(action="ADMIN_USER_UPDATE", target=username)
        .order_by(ActivityLog.id.desc())
        .one()
    )
    session.close()
    assert row.detail == {"fields": ["password"]}
    assert "brandnewpass1" not in str(row.detail)


def test_patch_of_an_unknown_id_is_404(client, admin):
    headers, _ = admin

    assert client.patch("/admin/users/99999999", headers=headers, json={"role": "USER"}).status_code == 404
    assert client.delete("/admin/users/99999999", headers=headers).status_code == 404


@pytest.mark.parametrize(
    "method,body",
    [
        ("patch", {"role": "USER"}),
        ("patch", {"is_active": False}),
        ("delete", None),
    ],
)
def test_the_last_active_admin_cannot_lose_their_rights(client, solo_admin, method, body):
    """The system must always keep one active ADMIN: losing the last one locks
    everybody out of the console, including the way back in.

    The self-guards answer these first -- an admin may not demote, deactivate or
    delete themselves -- so both orders end in 400. What is asserted is the
    invariant, not which of the two guards fired.
    """
    headers, username = solo_admin
    session = SessionLocal()
    user_id = session.query(User).filter_by(username=username).one().id
    session.close()
    assert _active_admins() == 1

    response = getattr(client, method)(
        f"/admin/users/{user_id}", headers=headers, **({"json": body} if body else {})
    )

    assert response.status_code == 400
    session = SessionLocal()
    still = session.query(User).filter_by(username=username).one()
    session.close()
    assert still.role == "ADMIN" and still.is_active
    assert _active_admins() == 1


def test_an_admin_can_promote_and_demote_another_account(client, admin):
    headers, _ = admin
    username = f"target-{uuid.uuid4().hex[:8]}"
    client.post("/admin/users", headers=headers, json={"username": username, "password": PASSWORD})
    user_id = client.get("/admin/users", headers=headers, params={"q": username}).json()[0]["id"]

    promoted = client.patch(f"/admin/users/{user_id}", headers=headers, json={"role": "ADMIN"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "ADMIN"

    # Now demoting them is fine: this actor is still an active admin.
    demoted = client.patch(f"/admin/users/{user_id}", headers=headers, json={"role": "USER"})
    assert demoted.status_code == 200 and demoted.json()["role"] == "USER"

    assert client.delete(f"/admin/users/{user_id}", headers=headers).status_code == 204
    session = SessionLocal()
    assert session.query(User).filter_by(username=username).one_or_none() is None
    session.close()


def test_list_users_reports_counts_and_filters(client, admin):
    headers, username = admin

    everyone = client.get("/admin/users", headers=headers, params={"limit": 500}).json()
    assert any(row["username"] == username for row in everyone)

    mine = client.get("/admin/users", headers=headers, params={"q": username}).json()
    assert [row["username"] for row in mine] == [username]
    assert set(mine[0]) == {"id", "username", "role", "is_active", "created_at", "sessions", "documents"}
