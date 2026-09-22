"""SP2 Task 4: the admin stats and knowledge-base routes.

Promotion is by hand here for the same reason it is by hand in the README: no
endpoint mints an admin (SP2 Decision 6).
"""
import uuid
from pathlib import Path

import pytest

from config import get_settings
from database import SessionLocal
from models import ActivityLog, Document, User

PASSWORD = "supersecret1"


def _make_account(client, prefix: str, role: str) -> dict[str, str]:
    username = f"{prefix}-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": PASSWORD})
    if role != "USER":
        session = SessionLocal()
        session.query(User).filter_by(username=username).update({"role": role})
        session.commit()
        session.close()
    token = client.post("/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(client) -> dict[str, str]:
    return _make_account(client, "adm", "ADMIN")


@pytest.fixture
def plain_user(client) -> dict[str, str]:
    return _make_account(client, "usr", "USER")


@pytest.fixture(autouse=True)
def cleanup():
    """Everything this module makes. Documents outlive their uploader
    (ON DELETE SET NULL), so they need their own sweep."""
    yield
    session = SessionLocal()
    session.query(Document).filter(Document.filename.like("%sp2doc-%")).delete(synchronize_session=False)
    session.query(ActivityLog).filter(ActivityLog.username.like("adm-%")).delete(synchronize_session=False)
    for prefix in ("adm-%", "usr-%"):
        session.query(User).filter(User.username.like(prefix)).delete(synchronize_session=False)
    session.commit()
    session.close()
    for stale in Path(get_settings().upload_dir).glob("*sp2doc-*"):
        stale.unlink(missing_ok=True)


@pytest.fixture
def embed_offline(monkeypatch):
    from services import document_service

    monkeypatch.setattr(document_service, "embed_texts", lambda texts: [[0.01] * 768 for _ in texts])


def _ingest(client, headers, body: str = "kebijakan cuti tahunan 12 hari") -> dict:
    """POST /documents the unique name this module cleans up by."""
    name = f"sp2doc-{uuid.uuid4().hex[:8]}.txt"
    response = client.post("/documents", headers=headers, files={"file": (name, body.encode(), "text/plain")})
    assert response.status_code == 200, response.text
    return response.json()


def test_user_role_is_forbidden_on_the_admin_routes(client, plain_user):
    """403, not 404: an admin surface is not a secret."""
    assert client.get("/admin/stats", headers=plain_user).status_code == 403
    assert client.get("/admin/documents", headers=plain_user).status_code == 403
    assert client.get("/admin/documents/x/chunks", headers=plain_user).status_code == 403
    assert client.delete("/admin/documents/x", headers=plain_user).status_code == 403
    assert client.get("/admin/stats").status_code == 401  # and no token at all


def test_stats_reports_counts_and_storage(client, admin, embed_offline):
    before = client.get("/admin/stats", headers=admin).json()
    _ingest(client, admin, "x" * 900)
    after = client.get("/admin/stats", headers=admin).json()

    assert after["documents"] == before["documents"] + 1
    assert after["chunks"] > before["chunks"]
    assert after["storage_bytes"] > before["storage_bytes"]
    assert after["users"] >= after["active_users"] >= 1


def test_admin_sees_one_row_per_ingested_file(client, admin, embed_offline):
    ingested = _ingest(client, admin, "x" * 900)

    rows = client.get("/admin/documents", headers=admin, params={"q": ingested["filename"]}).json()

    assert len(rows) == 1
    row = rows[0]
    assert row["filename"] == ingested["filename"]
    assert row["chunks"] == ingested["chunks"], "the row reports the chunker's own count"
    # Stored characters, not source characters: the chunker overlaps by 120, so the
    # sum is larger than the 900 in the file. The row must equal its own parts.
    chunks = client.get(f"/admin/documents/{ingested['filename']}/chunks", headers=admin).json()
    assert row["chars"] == sum(chunk["chars"] for chunk in chunks) > 900
    assert row["display_name"] == ingested["filename"].split("-", 1)[1]
    assert row["owner"] == _username_of(admin)
    assert row["created_at"]


def test_chunks_endpoint_returns_the_stored_text(client, admin, embed_offline):
    ingested = _ingest(client, admin)

    chunks = client.get(f"/admin/documents/{ingested['filename']}/chunks", headers=admin).json()

    assert len(chunks) == ingested["chunks"]
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["chars"] == len("kebijakan cuti tahunan 12 hari")
    assert "kebijakan cuti" in chunks[0]["content"]


def test_deleting_a_document_removes_chunks_file_and_writes_audit(client, admin, embed_offline):
    ingested = _ingest(client, admin)
    stored_file = Path(get_settings().upload_dir) / ingested["filename"]
    assert stored_file.exists()

    response = client.delete(f"/admin/documents/{ingested['filename']}", headers=admin)

    assert response.status_code == 204
    session = SessionLocal()
    assert session.query(Document).filter_by(filename=ingested["filename"]).count() == 0
    row = session.query(ActivityLog).filter_by(action="DOC_DELETE", target=ingested["filename"]).one()
    session.close()
    assert row.detail["chunks"] == ingested["chunks"]
    assert row.username == _username_of(admin)
    assert not stored_file.exists(), "the stored upload goes with the chunks"


def test_deleting_an_unknown_document_is_404(client, admin):
    assert client.delete(f"/admin/documents/sp2doc-{uuid.uuid4().hex}.txt", headers=admin).status_code == 404
    assert client.get(f"/admin/documents/sp2doc-{uuid.uuid4().hex}.txt/chunks", headers=admin).status_code == 404


@pytest.mark.parametrize(
    "attempt",
    [
        "..%2F..%2Fsp2-canary.txt",
        "..%2Fsp2-canary.txt",
        "...%2F...%2Fsp2-canary.txt",
    ],
)
def test_a_traversal_filename_deletes_nothing(client, admin, attempt):
    """Only the final path component may ever be joined, and the result must stay
    inside upload_dir. The canary sits one level above it."""
    upload_dir = Path(get_settings().upload_dir)
    canary = upload_dir.parent / "sp2-canary.txt"
    canary.write_text("must survive", encoding="utf-8")
    session = SessionLocal()
    documents_before = session.query(Document).count()
    session.close()

    response = client.delete(f"/admin/documents/{attempt}", headers=admin)

    assert response.status_code == 404
    assert canary.exists(), "the traversal reached outside upload_dir"
    session = SessionLocal()
    assert session.query(Document).count() == documents_before
    session.close()


def _username_of(headers: dict[str, str]) -> str:
    import base64
    import json as _json

    payload = headers["Authorization"].split(" ", 1)[1].split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return _json.loads(base64.urlsafe_b64decode(padded))["sub"]
