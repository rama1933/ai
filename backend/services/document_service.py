import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from sqlalchemy.orm import Session

from config import get_settings
from models import Document
from services.embedding_service import embed_texts

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
WHITESPACE = re.compile(r"\s+")

URL_TIMEOUT_SECONDS = 15.0
URL_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain", "text/markdown"}
# Block-level closes become a separator, so <p>a</p><p>b</p> does not read as "ab"
# while <b>ke</b>bijakan stays one word.
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "td", "th", "tr", "ul",
}


class IngestError(RuntimeError):
    """The file cannot be turned into indexable text."""


def load_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise IngestError(f"unsupported extension {suffix!r}; allowed: {sorted(SUPPORTED_EXTENSIONS)}")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8", errors="replace")


def clean_text(text: str) -> str:
    return WHITESPACE.sub(" ", CONTROL_CHARS.sub("", text)).strip()


class _VisibleText(HTMLParser):
    """Everything a reader came for: no script, style or template bodies, and no navigation, sidebar or footer chrome.

    Skipping reads the open-element stack rather than a count of skipped tags, because a
    count never recovers: a browser closes <nav> implicitly at the enclosing </header> and
    HTMLParser does not, so one dangling chrome tag dropped the rest of the page -- on a
    real news page with a single unclosed <aside>, 1,018 of 42,992 characters were stored
    and the ingest reported success.

    `head` is deliberately not skipped. Its open tag is optional in HTML5, so a page that
    omits `</head>` never pops it and it would stay on the stack for the whole document;
    the only text a head carries is the title, which is a fair description of the page.
    """

    SKIP = {"script", "style", "noscript", "template", "nav", "aside", "footer"}
    # Never pushed: nothing to pop, and a stray </br> must not close a real element.
    VOID = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._open: list[str] = []

    def _skipping(self) -> bool:
        return any(tag in self.SKIP for tag in self._open)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.VOID:
            self._open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        # Pop to the matching element, the way a browser closes an unclosed child: the
        # <nav> inside that <header> goes away with the </header>, so what follows reads.
        if tag in self._open:
            while self._open.pop() != tag:
                continue
        if not self._skipping() and tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping():
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Page markup down to its words.

    ponytail: a tag stripper, not a readability extractor. nav, aside and footer are
    dropped because measured retrieval ranked a fact at #11 behind its own page's
    menus; chrome built from plain divs still survives. Swap in a content extractor
    only if that measurably starts costing answers.
    """
    parser = _VisibleText()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def name_from_url(url: str) -> str:
    """A filename for a page: its last path segment, else the host."""
    parsed = urlparse(url.strip())
    return unquote(Path(parsed.path).name) or parsed.netloc


def fetch_url_text(url: str) -> str:
    """Read one web page as text.

    Fetched here and not in the browser: a browser fetch is subject to CORS, and what
    the corpus holds should not depend on the operator's proxy.

    Its caller (POST /documents/url) is admin-only, and this function leans on that:
    there is no private-address blocking, so an admin can point it at 127.0.0.1 or a
    cloud metadata address. That is the same trust the admin console already carries
    -- it can read every document and delete the corpus -- so it is not a widening.
    Anyone who exposes this behind a route a plain user can reach has to add the
    blocking first; a redirect hook too, since follow_redirects is on.
    """
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise IngestError("only http:// and https:// URLs can be ingested")

    cap = get_settings().max_upload_bytes
    # httpx's timeout is per operation and the read one resets on every byte, so a
    # server that dribbles a byte every few seconds would hold this worker -- and one
    # of the threadpool's slots -- for as long as it cared to. The deadline is the
    # wall-clock ceiling the per-read timeout is not. Checked per chunk, so it can
    # overrun by at most one chunk's wait.
    deadline = time.monotonic() + URL_TIMEOUT_SECONDS
    try:
        with httpx.stream(
            "GET", url, follow_redirects=True, timeout=URL_TIMEOUT_SECONDS, headers={"User-Agent": "agentic-rag/1.0"}
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type and content_type not in URL_CONTENT_TYPES:
                raise IngestError(f"{content_type} is not a readable page; allowed: {sorted(URL_CONTENT_TYPES)}")
            body = bytearray()
            for block in response.iter_bytes():
                body += block
                if len(body) > cap:
                    raise IngestError(f"{url} is larger than {cap} bytes")
                if time.monotonic() > deadline:
                    raise IngestError(f"{url} took longer than {URL_TIMEOUT_SECONDS}s to read")
    # InvalidURL does not descend from HTTPError, and urlparse accepts strings httpx
    # will not -- a control character in the host is enough. Without it that 500s.
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise IngestError(f"could not fetch {url}: {exc}") from exc

    # ponytail: UTF-8 or replacement characters. Non-UTF-8 legacy pages lose their
    # accents; honour response.encoding if that ever matters.
    text = body.decode("utf-8", errors="replace")
    return html_to_text(text) if "html" in content_type else text


def chunk_text(text: str, size: int = 800, overlap: int = 120) -> list[str]:
    """Fixed-window chunking with overlap.

    ponytail: character windows, not sentence- or token-aware splitting. Upgrade
    to a semantic splitter only if retrieval quality measurably suffers.
    """
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    if len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    step = size - overlap
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


def ingest_extract(
    db: Session,
    text: str,
    filename: str,
    user_id: int | None = None,
    source: str | None = None,
) -> int:
    """Chunk, embed and store text that was never a file: an image's OCR extract.

    Named for that caller and not `ingest_text`, which routers/documents.py already
    uses for the POST /documents/text handler -- a same-named import there would be
    shadowed by the route, and the shadow would be silent.

    Stored under whatever name the caller gives -- for an attachment, its stored
    name. The file and its text then share one handle, which is what lets the
    session scope in routers/chat.py find the extract on a LATER turn without
    knowing anything about images.

    Idempotent per filename, and it has to be: `documents` carries no unique key on
    it, so a second read of the same image would stack a second copy of its text in
    the corpus and every retrieval over it would return the same passage twice. The
    embeddings are computed BEFORE the old rows are dropped, so a failed embed leaves
    the previous extract in place instead of deleting it.
    """
    text = clean_text(text)
    if not text:
        raise IngestError(f"{filename} produced no extractable text")

    chunks = chunk_text(text)
    vectors = embed_texts(chunks)

    # The flush is load-bearing, not tidiness: a bulk DELETE does not autoflush, so rows
    # staged earlier in the SAME transaction -- the read-first OCR of this very image,
    # when the model then calls image_ocr for it again -- would be invisible to the
    # DELETE and survive it as a second copy of the same text.
    db.flush()
    db.query(Document).filter(Document.filename == filename).delete(synchronize_session=False)
    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        db.add(
            Document(
                filename=filename,
                content=chunk,
                embedding=vector,
                user_id=user_id,
                doc_metadata={"chunk_index": index, "chunk_count": len(chunks), "source": source or filename},
            )
        )
    return len(chunks)


def ingest_file(db: Session, path: Path, user_id: int | None = None) -> int:
    """Load, clean, chunk, embed, and store a file. Returns the chunk count.

    user_id records provenance only. The corpus is shared by design, so retrieval
    ignores it; it exists so per-user filtering is a one-line change later rather
    than another migration.
    """
    return ingest_extract(db, load_text(path), path.name, user_id, source=str(path))
