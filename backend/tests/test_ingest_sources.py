"""The three ways a document gets in: a file, pasted text, a URL.

All three end as the same thing on disk -- `{uuid}-{name}.txt` in upload_dir -- which
is what keeps DELETE /admin/documents and the storage total working unchanged.
"""
import time
import uuid
from pathlib import Path

import pytest

from config import get_settings
from database import SessionLocal
from models import Document, User
from services import document_service
from services.upload_service import UploadRejected, store_text_file

PASSWORD = "supersecret1"

PAGE = """<html><head><title>Kebijakan Cuti</title>
<style>p{color:red}</style></head>
<body><script>var x = "jangan dibaca";</script>
<h1>Kebijakan Cuti</h1><p>Cuti tahunan <b>12</b> hari.</p>
<p>Pengajuan lewat <a href="/x">atasan</a> langsung.</p>
<footer>Hak cipta 2026</footer>
</body></html>"""


def _account(client, prefix: str, role: str) -> dict[str, str]:
    """Registration is open and hands out USER, so an admin is promoted by hand --
    the same way the README and tests/test_admin_documents.py do it."""
    username = f"{prefix}-{uuid.uuid4().hex[:8]}"
    client.post("/auth/register", json={"username": username, "password": PASSWORD})
    if role != "USER":
        session = SessionLocal()
        session.query(User).filter_by(username=username).update({"role": role})
        session.commit()
        session.close()
    token = client.post("/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def cleanup():
    """Everything this module makes: the accounts, their documents, their files."""
    yield
    session = SessionLocal()
    session.query(Document).filter(Document.filename.like("%ing-")).delete(synchronize_session=False)
    session.query(User).filter(User.username.like("ing-%")).delete(synchronize_session=False)
    session.commit()
    session.close()
    for stale in Path(get_settings().upload_dir).glob("*ing-*"):
        stale.unlink(missing_ok=True)


@pytest.fixture
def auth(client) -> dict[str, str]:
    """A plain signed-in user. Enough for text, not for fetching a URL."""
    return _account(client, "ing", "USER")


@pytest.fixture
def admin(client) -> dict[str, str]:
    """POST /documents/url opens a socket to an address the caller picked, so it is
    behind the same role guard as the rest of the console."""
    return _account(client, "ing", "ADMIN")


@pytest.fixture
def embed_offline(monkeypatch):
    monkeypatch.setattr(document_service, "embed_texts", lambda texts: [[0.01] * 768 for _ in texts])


def test_html_to_text_keeps_the_prose_and_drops_the_chrome():
    text = document_service.clean_text(document_service.html_to_text(PAGE))

    assert "Cuti tahunan 12 hari." in text, "inline markup must not split a word"
    assert "atasan" in text
    assert "jangan dibaca" not in text, "script bodies are not knowledge"
    assert "color:red" not in text, "style bodies are not knowledge"
    # Block closes separate, so two paragraphs never read as one word.
    assert "hari. Pengajuan" in text


def test_html_to_text_drops_navigation_and_footer():
    """Measured: on a menu-heavy page the fact was 10% of its chunk and ranked #11.
    Navigation, sidebars and footers are chrome, not knowledge."""
    menu = "<li><a>Beranda Profil Berita Layanan PPID Kontak</a></li>" * 10
    page = (
        f"<html><body><nav><ul>{menu}</ul></nav><aside>Berita terpopuler</aside>"
        "<main><h1>Retribusi Pasar</h1><p>Tarif Rp 5.000 per lapak per hari.</p></main>"
        f"<footer>{menu} Hak cipta 2026</footer></body></html>"
    )

    text = document_service.clean_text(document_service.html_to_text(page))

    assert text == "Retribusi Pasar Tarif Rp 5.000 per lapak per hari."
    assert document_service.clean_text(document_service.html_to_text(f"<nav>{menu}</nav>")) == "", (
        "a page that is all navigation reads as empty and is refused, not stored"
    )


def test_name_from_url_prefers_the_last_segment_then_the_host():
    assert document_service.name_from_url("https://contoh.id/docs/kebijakan-cuti.html") == "kebijakan-cuti.html"
    assert document_service.name_from_url("https://contoh.id/") == "contoh.id"


def test_fetch_url_text_refuses_anything_that_is_not_http():
    for bad in ("file:///etc/passwd", "ftp://contoh.id/x", "contoh.id/docs"):
        with pytest.raises(document_service.IngestError, match="http"):
            document_service.fetch_url_text(bad)


def test_store_text_file_replaces_the_extension_it_was_handed(tmp_path):
    stored = store_text_file("kebijakan cuti", "catatan/../Kebijakan Cuti.html")

    assert stored.suffix == ".txt"
    assert stored.parent == Path(get_settings().upload_dir)
    assert document_service.load_text(stored) == "kebijakan cuti"
    stored.unlink()


def test_store_text_file_rejects_text_with_nothing_in_it():
    with pytest.raises(UploadRejected, match="empty"):
        store_text_file("   \n  ", "kosong")


def test_pasted_text_is_ingested_as_a_document_of_its_own(client, auth, embed_offline):
    name = f"ing-{uuid.uuid4().hex[:8]}"
    response = client.post("/documents/text", headers=auth, json={"title": name, "content": "cuti tahunan 12 hari"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"].endswith(f"{name}.txt") and body["chunks"] == 1

    session = SessionLocal()
    try:
        row = session.query(Document).filter(Document.filename == body["filename"]).one()
        # The title is embedded with the body: a short note ("cuti tahunan 12 hari")
        # asked about by its title missed the top four until it was.
        assert row.content == f"{name} cuti tahunan 12 hari"
    finally:
        session.close()


def test_a_url_is_fetched_and_stored_as_text(client, admin, embed_offline, monkeypatch):
    # Patched where the route looks it up, not where it is defined: the router holds
    # its own reference, and patching document_service would leave it untouched.
    monkeypatch.setattr("routers.documents.fetch_url_text", lambda url: document_service.html_to_text(PAGE))
    name = f"ing-{uuid.uuid4().hex[:8]}"

    response = client.post("/documents/url", headers=admin, json={"url": "https://contoh.id/docs/x", "title": name})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"].endswith(f"{name}.txt")

    session = SessionLocal()
    try:
        row = session.query(Document).filter(Document.filename == body["filename"]).one()
        assert "Cuti tahunan 12 hari." in row.content
        assert row.content.startswith(name), "the operator's title leads the page text"
        assert row.doc_metadata["source"].endswith(f"{name}.txt"), "the source is the stored file, not the URL"
    finally:
        session.close()


def test_a_plain_user_may_paste_text_but_not_point_the_server_at_a_url(client, auth, embed_offline):
    """The two new routes are not the same privilege: one stores what the caller
    already has, the other makes this host open a socket to an address of their
    choosing -- 127.0.0.1 and cloud metadata included, and the page it reads back
    lands in the corpus every user can query."""
    assert client.post("/documents/text", headers=auth, json={"content": "cuti 12 hari"}).status_code == 200

    refused = client.post("/documents/url", headers=auth, json={"url": "http://127.0.0.1:8000/health"})

    assert refused.status_code == 403
    assert refused.json()["detail"] == "requires role in ('ADMIN',)"


def test_a_url_that_cannot_be_read_is_a_422_and_leaves_nothing_behind(client, admin, embed_offline):
    before = set(Path(get_settings().upload_dir).glob("*"))

    response = client.post("/documents/url", headers=admin, json={"url": "file:///etc/passwd"})

    assert response.status_code == 422
    assert "http" in response.json()["detail"]
    assert set(Path(get_settings().upload_dir).glob("*")) == before, "nothing was written"


def test_a_url_httpx_rejects_is_a_422_not_a_500(client, admin, embed_offline):
    """urlparse accepts a control character in the host; httpx raises InvalidURL,
    which is not an HTTPError, so it used to escape as a 500."""
    for bad in ("http://contoh.id/a\x00b", "http://contoh.id/a\nb"):
        response = client.post("/documents/url", headers=admin, json={"url": bad})
        assert response.status_code == 422, f"{bad!r} leaked {response.status_code}"


def test_a_slow_drip_of_bytes_cannot_hold_the_worker(monkeypatch):
    """httpx's read timeout resets on every byte, so a server that trickles bytes
    would keep the request alive until the size cap. The deadline is what bounds it."""
    monkeypatch.setattr(document_service, "URL_TIMEOUT_SECONDS", 0.3)

    class Drip:
        """A response that never ends and never pauses long enough to time out."""

        headers = {"content-type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            while True:
                time.sleep(0.05)
                yield b"x"

    monkeypatch.setattr(document_service.httpx, "stream", lambda *a, **kw: Drip())

    started = time.monotonic()
    with pytest.raises(document_service.IngestError, match="took longer"):
        document_service.fetch_url_text("http://contoh.id/lambat")

    assert time.monotonic() - started < 5, "the deadline, not the size cap, ended it"


def test_html_with_an_unclosed_head_still_reads(client, admin, embed_offline, monkeypatch):
    """HTML5 lets </head> be dropped. Counting it as an unclosed block used to swallow
    the rest of the document and fail the ingest with 'no extractable text'."""
    monkeypatch.setattr(
        "routers.documents.fetch_url_text",
        lambda url: document_service.html_to_text("<html><head><title>Judul</title><body><p>Halo dunia.</p>"),
    )

    response = client.post("/documents/url", headers=admin, json={"url": "https://contoh.id/x"})

    assert response.status_code == 200, response.text
    session = SessionLocal()
    try:
        row = session.query(Document).filter(Document.filename == response.json()["filename"]).one()
        assert "Halo dunia." in row.content
    finally:
        session.close()


def test_text_that_cleans_down_to_nothing_takes_its_file_with_it(client, auth, embed_offline):
    name = f"ing-{uuid.uuid4().hex[:8]}"
    response = client.post("/documents/text", headers=auth, json={"title": name, "content": "\x00\x00"})

    assert response.status_code == 422
    assert list(Path(get_settings().upload_dir).glob(f"*{name}*")) == [], "the orphan file was removed"


def test_empty_text_is_refused_at_the_edge(client, auth):
    assert client.post("/documents/text", headers=auth, json={"title": "x", "content": ""}).status_code == 422


def test_titled_leaves_empty_text_empty():
    """A title must not rescue a body that cleans down to nothing -- the empty-text
    refusals downstream have to keep firing."""
    from routers.documents import _titled

    assert _titled("Jadwal KTP", "Selasa 08.00") == "Jadwal KTP\n\nSelasa 08.00"
    assert _titled(None, "Selasa 08.00") == "Selasa 08.00"
    assert _titled("Jadwal KTP", "\x00\x00") == "\x00\x00"
    assert _titled("Jadwal KTP", "   ") == "   "
