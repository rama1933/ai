"""Attachments: persisted on the message, re-derived from disk, served owner-scoped."""
import base64
import io
import json
import uuid
from pathlib import Path

import pytest

from agent import registry
from agent.orchestrator import AgentResult
from database import SessionLocal
from models import Document, User
from schemas import SourceRef

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
UPLOAD_DIR = Path("../storage/uploads")

# A minimal structurally valid PDF whose text pypdf can extract, so the ingest
# branch accepts it.
_PDF_STREAM = b"BT /F1 18 Tf 72 720 Td (Laporan anggaran 2026: total Rp 250 juta.) Tj ET"
_PDF_OBJS = [
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n",
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n",
    b"4 0 obj<</Length " + str(len(_PDF_STREAM)).encode() + b">>stream\n" + _PDF_STREAM + b"\nendstream\nendobj\n",
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
]


def _build_pdf() -> bytes:
    header, body, offsets = b"%PDF-1.4\n", b"", []
    for obj in _PDF_OBJS:
        offsets.append(len(header) + len(body))
        body += obj
    xref_pos = len(header) + len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n" + b"".join(("%010d 00000 n \n" % off).encode() for off in offsets)
    trailer = b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    return header + body + xref + trailer


PDF_VALID = _build_pdf()


def _username_of(headers: dict[str, str]) -> str:
    payload = headers["Authorization"].split(" ", 1)[1].split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["sub"]


@pytest.fixture
def auth_headers(client) -> dict[str, str]:
    username = f"attach-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": "supersecret1"})
    token = client.post("/auth/login", json={"username": username, "password": "supersecret1"}).json()["access_token"]
    yield {"Authorization": f"Bearer {token}"}
    session = SessionLocal()
    session.query(User).filter(User.username.like("attach-%")).delete(synchronize_session=False)
    session.commit()
    session.close()


@pytest.fixture
def quiet_agent(monkeypatch):
    from routers import chat as chat_router

    monkeypatch.setattr(
        chat_router,
        "run_agent",
        lambda db, message, history, image_paths, document_filenames=None: AgentResult(answer="ok", tool_used=None, sources=[]),
    )


@pytest.fixture
def session_id() -> str:
    sid = f"attach-{uuid.uuid4().hex[:8]}"
    yield sid
    session = SessionLocal()
    from models import ChatSession

    session.query(ChatSession).filter_by(id=sid).delete(synchronize_session=False)
    session.commit()
    session.close()


def _upload(client, headers: dict, name: str, content: bytes, mime: str) -> dict:
    response = client.post("/upload", headers=headers, files={"file": (name, io.BytesIO(content), mime)})
    assert response.status_code == 200, response.text
    body = response.json()
    (UPLOAD_DIR / body["stored_name"]).unlink(missing_ok=True)  # already on disk; keep the tree clean
    return body


def _store_on_disk(body: dict, content: bytes) -> None:
    """Re-materialise an uploaded payload: some tests need the file present."""
    (UPLOAD_DIR / body["stored_name"]).write_bytes(content)


def test_upload_response_carries_the_richer_fields(client, auth_headers):
    up = _upload(client, auth_headers, "struk.png", PNG, "image/png")

    assert up["filename"] == up["stored_name"]
    assert up["stored_name"].endswith("struk.png")
    assert up["display_name"] == "struk.png"
    assert up["kind"] == "image"
    assert up["mime"] == "image/png"
    assert up["size"] == len(PNG)


def test_message_round_trips_attachments_through_history(client, auth_headers, quiet_agent, session_id):
    up = _upload(client, auth_headers, "struk.png", PNG, "image/png")
    _store_on_disk(up, PNG)
    sent = client.post(
        "/chat",
        headers=auth_headers,
        json={"session_id": session_id, "message": "lihat struk", "attachments": [up["stored_name"]]},
    )
    assert sent.status_code == 200

    history = client.get(f"/chat/history?session_id={session_id}", headers=auth_headers).json()

    user_row = next(r for r in history if r["role"] == "user")
    assert user_row["attachments"] == [
        {
            "stored_name": up["stored_name"],
            "display_name": "struk.png",
            "kind": "image",
            "mime": "image/png",
            "size": len(PNG),
        }
    ]
    assert history[-1]["attachments"] == []
    (UPLOAD_DIR / up["stored_name"]).unlink(missing_ok=True)


def test_only_images_reach_the_agent_as_image_paths(client, auth_headers, session_id, monkeypatch):
    from routers import chat as chat_router

    captured = {}

    def fake_run_agent(db, message, history, image_paths, document_filenames=None):
        captured["image_paths"] = image_paths
        return AgentResult(answer="ok", tool_used=None, sources=[])

    monkeypatch.setattr(chat_router, "run_agent", fake_run_agent)
    from services import document_service

    monkeypatch.setattr(document_service, "embed_texts", lambda texts: [[0.01] * 768 for _ in texts])

    png = _upload(client, auth_headers, "struk.png", PNG, "image/png")
    txt = _upload(client, auth_headers, "catatan.txt", "ini catatan".encode(), "text/plain")
    _store_on_disk(png, PNG)
    _store_on_disk(txt, b"ini catatan")
    response = client.post(
        "/chat",
        headers=auth_headers,
        json={
            "session_id": session_id,
            "message": "lihat keduanya",
            "attachments": [png["stored_name"], txt["stored_name"]],
        },
    )
    assert response.status_code == 200

    assert len(captured["image_paths"]) == 1
    assert captured["image_paths"][0].endswith("struk.png")
    (UPLOAD_DIR / png["stored_name"]).unlink(missing_ok=True)
    (UPLOAD_DIR / txt["stored_name"]).unlink(missing_ok=True)


def test_image_ocr_reads_every_attached_image(monkeypatch):
    """The tool runs over the whole list under per-file headers; zero parameters stay zero."""
    seen = []
    monkeypatch.setattr(registry, "image_ocr", lambda path: seen.append(path) or f"teks dari {Path(path).name}")

    outcome = registry.dispatch(
        "image_ocr", {}, db=None, image_paths=["/somewhere/aaa-struk-a.png", "/somewhere/bbb-struk-b.png"]
    )

    assert len(seen) == 2
    assert "[aaa-struk-a.png]" in outcome.text
    assert "[bbb-struk-b.png]" in outcome.text
    assert registry.UNTRUSTED_HEADER in outcome.text
    assert [s.filename for s in outcome.sources] == ["aaa-struk-a.png", "bbb-struk-b.png"]


def test_image_ocr_reports_a_failed_image_and_keeps_the_rest(monkeypatch):
    from tools.ocr_tool import OcrError

    def flaky(path):
        if "broken" in path:
            raise OcrError("cannot decode image")
        return "teks bagus"

    monkeypatch.setattr(registry, "image_ocr", flaky)

    outcome = registry.dispatch(
        "image_ocr", {}, db=None, image_paths=["/somewhere/aaa-broken.png", "/somewhere/bbb-good.png"]
    )

    assert "OCR failed" in outcome.text
    assert "teks bagus" in outcome.text
    assert [s.filename for s in outcome.sources] == ["bbb-good.png"]


def test_attachment_serves_to_its_owner_with_display_name_and_mime(client, auth_headers, quiet_agent, session_id):
    up = _upload(client, auth_headers, "struk.png", PNG, "image/png")
    _store_on_disk(up, PNG)
    client.post(
        "/chat",
        headers=auth_headers,
        json={"session_id": session_id, "message": "lihat", "attachments": [up["stored_name"]]},
    )

    response = client.get(f"/attachments/{up['stored_name']}", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert "struk.png" in response.headers["content-disposition"]
    assert response.content == PNG
    (UPLOAD_DIR / up["stored_name"]).unlink(missing_ok=True)


def test_attachment_of_another_users_conversation_is_404(client, auth_headers, quiet_agent):
    username_b = f"attach-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username_b, "password": "supersecret1"})
    token_b = client.post("/auth/login", json={"username": username_b, "password": "supersecret1"}).json()[
        "access_token"
    ]
    headers_b = {"Authorization": f"Bearer {token_b}"}
    sid_b = f"attach-{uuid.uuid4().hex[:8]}"
    up = _upload(client, headers_b, "struk-b.png", PNG, "image/png")
    _store_on_disk(up, PNG)
    client.post(
        "/chat",
        headers=headers_b,
        json={"session_id": sid_b, "message": "lihat", "attachments": [up["stored_name"]]},
    )

    foreign = client.get(f"/attachments/{up['stored_name']}", headers=auth_headers)
    own = client.get(f"/attachments/{up['stored_name']}", headers=headers_b)

    assert foreign.status_code == 404
    assert own.status_code == 200
    (UPLOAD_DIR / up["stored_name"]).unlink(missing_ok=True)


def test_traversal_and_absolute_names_are_404(client, auth_headers):
    for name in ("%2E%2E%2Fdb%2Fschema.sql", "%2Fetc%2Fpasswd", "..%2Fuploads.png"):
        response = client.get(f"/attachments/{name}", headers=auth_headers)
        assert response.status_code == 404, name


def test_upload_that_was_never_sent_is_not_servable(client, auth_headers):
    up = _upload(client, auth_headers, "struk.png", PNG, "image/png")

    response = client.get(f"/attachments/{up['stored_name']}", headers=auth_headers)

    assert response.status_code == 404
    (UPLOAD_DIR / up["stored_name"]).unlink(missing_ok=True)


def test_more_than_five_attachments_is_rejected_at_validation(client, auth_headers, session_id):
    response = client.post(
        "/chat",
        headers=auth_headers,
        json={
            "session_id": session_id,
            "message": "banyak sekaligus",
            "attachments": [f"file-{i}.png" for i in range(6)],
        },
    )

    assert response.status_code == 422


def test_session_documents_thread_to_the_agent_for_retrieval_scoping(
    client, auth_headers, session_id, monkeypatch
):
    """A document uploaded earlier in the conversation scopes later retrieval:
    'pelajari dokumen ini' must anchor to it, not to the whole shared corpus."""
    from routers import chat as chat_router

    captured = {}

    def fake_run_agent(db, message, history, image_paths, document_filenames=None):
        captured["document_filenames"] = document_filenames
        return AgentResult(answer="ok", tool_used=None, sources=[])

    monkeypatch.setattr(chat_router, "run_agent", fake_run_agent)
    from services import document_service

    monkeypatch.setattr(document_service, "embed_texts", lambda texts: [[0.01] * 768 for _ in texts])

    first = _upload(client, auth_headers, "laporan.txt", "isi laporan pertama".encode(), "text/plain")
    _store_on_disk(first, b"isi laporan pertama")
    second = _upload(client, auth_headers, "keputusan.pdf", PDF_VALID, "application/pdf")
    _store_on_disk(second, PDF_VALID)

    # Documents enter session history only through message attachments: send
    # one message per document, then a bare question.
    client.post(
        "/chat",
        headers=auth_headers,
        json={"session_id": session_id, "message": "pelajari yang ini", "attachments": [first["stored_name"]]},
    )
    client.post(
        "/chat",
        headers=auth_headers,
        json={"session_id": session_id, "message": "dan yang ini", "attachments": [second["stored_name"]]},
    )
    client.post(
        "/chat",
        headers=auth_headers,
        json={"session_id": session_id, "message": "pelajari dokumen ini"},
    )

    assert captured["document_filenames"] == [second["stored_name"], first["stored_name"]]  # newest first

    # The ingested chunks land in the shared corpus; clean them up.
    session = SessionLocal()
    session.query(Document).filter(
        Document.filename.in_([first["stored_name"], second["stored_name"]])
    ).delete(synchronize_session=False)
    session.commit()
    session.close()
    (UPLOAD_DIR / first["stored_name"]).unlink(missing_ok=True)
    (UPLOAD_DIR / second["stored_name"]).unlink(missing_ok=True)
