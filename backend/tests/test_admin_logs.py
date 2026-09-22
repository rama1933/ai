"""SP2 Task 5: the activity log routes -- filter, actions, retention purge."""
import uuid
from datetime import datetime, timedelta

import pytest

from database import SessionLocal
from models import ActivityLog, User

PASSWORD = "supersecret1"


def _make_account(client, prefix: str, role: str) -> tuple[str, dict[str, str]]:
    username = f"{prefix}-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": PASSWORD})
    if role != "USER":
        session = SessionLocal()
        session.query(User).filter_by(username=username).update({"role": role})
        session.commit()
        session.close()
    token = client.post("/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    return username, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(client) -> tuple[str, dict[str, str]]:
    return _make_account(client, "adm", "ADMIN")


@pytest.fixture
def plain_user(client) -> dict[str, str]:
    return _make_account(client, "usr", "USER")[1]


@pytest.fixture
def marker() -> str:
    """Rows this module owns are addressed by a target of this name."""
    return f"sp2log-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def cleanup():
    yield
    session = SessionLocal()
    session.query(ActivityLog).filter(ActivityLog.target.like("sp2log-%")).delete(synchronize_session=False)
    session.query(ActivityLog).filter(ActivityLog.username.like("adm-%")).delete(synchronize_session=False)
    for prefix in ("adm-%", "usr-%"):
        session.query(User).filter(User.username.like(prefix)).delete(synchronize_session=False)
    session.commit()
    session.close()


def _seed(marker: str, action: str, username: str | None, created_at: datetime | None = None) -> int:
    session = SessionLocal()
    row = ActivityLog(username=username, action=action, target=marker, detail={"seeded": True})
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    session.commit()
    row_id = row.id
    session.close()
    return row_id


def _targets(response) -> list[str]:
    return [row["target"] for row in response.json()]


def test_user_role_is_forbidden_on_the_log_routes(client, plain_user):
    assert client.get("/admin/logs", headers=plain_user).status_code == 403
    assert client.get("/admin/logs/actions", headers=plain_user).status_code == 403
    assert client.delete("/admin/logs?before=2026-01-01T00:00:00", headers=plain_user).status_code == 403


def test_filtering_by_action_narrows_the_result(client, admin, marker):
    _, headers = admin
    _seed(marker, "DOC_INGEST", "someone")
    _seed(marker, "DOC_DELETE", "someone")

    filtered = client.get("/admin/logs", headers=headers, params={"action": "DOC_INGEST", "limit": 500})

    assert filtered.status_code == 200
    rows = [row for row in filtered.json() if row["target"] == marker]
    assert [row["action"] for row in rows] == ["DOC_INGEST"]


def test_filtering_by_username_narrows_the_result(client, admin, marker):
    _, headers = admin
    mine, theirs = f"{marker}-mine", f"{marker}-theirs"
    _seed(mine, "DOC_INGEST", "adm-fixed-name")
    _seed(theirs, "DOC_INGEST", "somebody-else")

    filtered = client.get("/admin/logs", headers=headers, params={"username": "adm-fixed-name"})

    targets = _targets(filtered)
    assert mine in targets
    assert theirs not in targets


def test_username_filter_also_matches_a_failed_login(client, admin, marker):
    """A failed login carries the attempted name in detail and no account row: the
    filter has to reach it, or the interesting rows are the ones it hides."""
    _, headers = admin
    session = SessionLocal()
    session.add(
        ActivityLog(username=None, action="AUTH_LOGIN_FAILED", target=marker, detail={"username": "adm-ghost"})
    )
    session.commit()
    session.close()

    filtered = client.get("/admin/logs", headers=headers, params={"username": "adm-ghost"})

    assert marker in _targets(filtered)


def test_logs_are_newest_first(client, admin, marker):
    _, headers = admin
    for _ in range(3):
        _seed(marker, "DOC_INGEST", "someone")

    page = client.get("/admin/logs", headers=headers, params={"limit": 500}).json()
    ids = [row["id"] for row in page]
    assert ids == sorted(ids, reverse=True)


def test_actions_endpoint_lists_what_is_present(client, admin, marker):
    _, headers = admin
    _seed(marker, "ADMIN_LOG_PURGE", "someone")

    actions = client.get("/admin/logs/actions", headers=headers).json()

    assert "ADMIN_LOG_PURGE" in actions
    assert actions == sorted(actions)


def test_purge_deletes_only_rows_older_than_before(client, admin, marker):
    username, headers = admin
    old = datetime.now() - timedelta(days=30)
    fresh = datetime.now() - timedelta(minutes=5)
    old_id = _seed(marker, "DOC_INGEST", "someone", created_at=old)
    fresh_id = _seed(marker, "DOC_INGEST", "someone", created_at=fresh)
    before = (datetime.now() - timedelta(days=1)).isoformat()

    response = client.delete("/admin/logs", headers=headers, params={"before": before})

    assert response.status_code == 200
    assert response.json()["deleted"] >= 1
    session = SessionLocal()
    assert session.query(ActivityLog).filter_by(id=old_id).one_or_none() is None
    assert session.query(ActivityLog).filter_by(id=fresh_id).one_or_none() is not None
    purge = (
        session.query(ActivityLog)
        .filter_by(action="ADMIN_LOG_PURGE", username=username)
        .order_by(ActivityLog.id.desc())
        .first()
    )
    session.close()
    assert purge is not None, "the purge audits itself"
    assert purge.detail["deleted"] >= 1


def test_purge_requires_a_date(client, admin):
    _, headers = admin

    assert client.delete("/admin/logs", headers=headers).status_code == 422
