import io
import uuid

import pytest

from database import SessionLocal
from models import User


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


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_upload_requires_authentication(client):
    response = client.post("/upload", files={"file": ("struk.png", io.BytesIO(PNG), "image/png")})
    assert response.status_code == 401


def test_upload_image_returns_stored_name(client, auth_headers):
    response = client.post(
        "/upload", headers=auth_headers, files={"file": ("struk.png", io.BytesIO(PNG), "image/png")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "image"
    assert body["status"] == "stored"
    assert body["filename"].endswith("struk.png")


def test_upload_of_an_unreadable_document_leaves_nothing_behind(client, auth_headers, monkeypatch):
    """A stored file that never became chunks must not survive the failure.

    The request rolls back, so the UPLOAD_STORE row goes with it; if the file stayed
    it would be invisible to both the knowledge screen and the log while still being
    counted in the console's storage total.
    """
    from pathlib import Path

    from config import get_settings
    from services import document_service

    monkeypatch.setattr(document_service, "embed_texts", lambda texts: [[0.01] * 768 for _ in texts])
    # Whitespace cleans down to nothing, which is an IngestError -- the shape a scanned
    # PDF with no text layer takes.
    before = set(Path(get_settings().upload_dir).glob("*sp2-empty-*"))

    response = client.post(
        "/upload",
        headers=auth_headers,
        files={"file": ("sp2-empty-probe.txt", io.BytesIO(b"   \n\t  "), "text/plain")},
    )

    assert response.status_code == 422, response.text
    assert set(Path(get_settings().upload_dir).glob("*sp2-empty-*")) == before


def test_upload_rejects_executable(client, auth_headers):
    response = client.post(
        "/upload",
        headers=auth_headers,
        files={"file": ("payload.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "extension" in response.json()["detail"]
