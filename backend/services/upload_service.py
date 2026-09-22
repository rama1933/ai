import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from config import get_settings

READ_CHUNK = 64 * 1024
UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")

# Text formats have no magic number, but a file claiming to be text must not
# actually begin with a known binary header.
BINARY_SIGNATURES: tuple[bytes, ...] = (
    b"%PDF",
    b"\x7fELF",
    b"MZ",
    b"\x89PNG",
    b"\xff\xd8\xff",
    b"PK\x03\x04",
    b"\x1f\x8b",
    b"\xca\xfe\xba\xbe",
)
TEXT_SUFFIXES = {".txt", ".md"}

# extension -> (kind, allowed MIME types, magic prefixes; empty tuple = no signature check)
RULES: dict[str, tuple[str, set[str], tuple[bytes, ...]]] = {
    ".png": ("image", {"image/png"}, (b"\x89PNG\r\n\x1a\n",)),
    ".jpg": ("image", {"image/jpeg"}, (b"\xff\xd8\xff",)),
    ".jpeg": ("image", {"image/jpeg"}, (b"\xff\xd8\xff",)),
    ".webp": ("image", {"image/webp"}, (b"RIFF",)),
    ".pdf": ("document", {"application/pdf"}, (b"%PDF",)),
    ".txt": ("document", {"text/plain", "application/octet-stream"}, ()),
    ".md": ("document", {"text/markdown", "text/plain", "application/octet-stream"}, ()),
}


class UploadRejected(ValueError):
    """The uploaded file failed validation and was not stored."""


def _looks_like_text(head: bytes) -> bool:
    """True when head (the first chunk of the file) is plausible UTF-8 text."""
    if any(head.startswith(sig) for sig in BINARY_SIGNATURES):
        return False
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        # The chunk boundary can split a multibyte character; drop the tail
        # bytes that might belong to an incomplete sequence and retry.
        try:
            head[:-4].decode("utf-8")
        except UnicodeDecodeError:
            return False
    return True


def _check_signature(suffix: str, signatures: tuple[bytes, ...], head: bytes) -> None:
    if signatures and not any(head.startswith(sig) for sig in signatures):
        raise UploadRejected(f"file signature does not match extension {suffix!r}")
    if suffix in TEXT_SUFFIXES and not _looks_like_text(head):
        raise UploadRejected(f"file signature does not match extension {suffix!r}")


def classify(filename: str, content_type: str, head: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    rule = RULES.get(suffix)
    if rule is None:
        raise UploadRejected(f"extension {suffix!r} is not allowed; allowed: {sorted(RULES)}")

    kind, allowed_mimes, signatures = rule
    if content_type.split(";")[0].strip() not in allowed_mimes:
        raise UploadRejected(f"MIME type {content_type!r} does not match extension {suffix!r}")
    _check_signature(suffix, signatures, head)
    return kind


def sniff(filename: str, head: bytes) -> tuple[str, str]:
    """Derive (kind, mime) from the file on disk, never from client metadata.

    A message references its attachments by stored name only, so the kind that
    picks the OCR branch is re-derived here at chat time: a caller cannot mislabel
    a payload as an image.
    """
    suffix = Path(filename).suffix.lower()
    rule = RULES.get(suffix)
    if rule is None:
        raise UploadRejected(f"extension {suffix!r} is not allowed; allowed: {sorted(RULES)}")
    kind, allowed_mimes, signatures = rule
    _check_signature(suffix, signatures, head)
    # The canonical member of the rule's allowed set; text rules also allow
    # application/octet-stream, which is the fallback, never the answer.
    mime = next((m for m in sorted(allowed_mimes) if m != "application/octet-stream"), "application/octet-stream")
    return kind, mime


def display_name_of(stored_name: str) -> str:
    """stored.name minus the `{uuid4() hex}-` prefix save_upload prepends."""
    prefix, sep, rest = stored_name.partition("-")
    if sep and len(prefix) == 32 and all(c in "0123456789abcdef" for c in prefix):
        return rest
    return stored_name


def _safe_name(filename: str) -> str:
    stem = Path(filename).name  # drops any directory traversal
    return UNSAFE_NAME_CHARS.sub("_", stem)


def store_text_file(text: str, name: str) -> Path:
    """Write pasted or fetched text to disk under a stored name and return it.

    Text and URL ingests are put in the same shape as an upload -- `{uuid}-{name}.txt`
    in upload_dir -- so the corpus, the storage total and DELETE /admin/documents
    keep working on one kind of thing rather than three.
    """
    settings = get_settings()
    payload = text.encode("utf-8")
    if not payload.strip():
        raise UploadRejected("text is empty")
    if len(payload) > settings.max_upload_bytes:
        raise UploadRejected(f"text size exceeds {settings.max_upload_bytes} bytes")

    # A title typed as a filename keeps its meaning, not its extension: the stored
    # .txt is what load_text recognises, so whatever came in has to give way to it.
    stem = re.sub(r"\.(txt|md|pdf|x?html?)$", "", _safe_name(name)[:80], flags=re.IGNORECASE) or "catatan"

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"{uuid.uuid4().hex}-{stem}.txt"
    target.write_bytes(payload)
    return target


def save_upload(file: UploadFile, allowed_kinds: set[str]) -> Path:
    settings = get_settings()
    head = file.file.read(READ_CHUNK)
    file.file.seek(0)

    kind = classify(file.filename or "", file.content_type or "", head)
    if kind not in allowed_kinds:
        raise UploadRejected(f"{kind} files are not accepted by this endpoint")

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"{uuid.uuid4().hex}-{_safe_name(file.filename or 'upload')}"

    written = 0
    with target.open("wb") as out:
        while chunk := file.file.read(READ_CHUNK):
            written += len(chunk)
            if written > settings.max_upload_bytes:
                out.close()
                target.unlink(missing_ok=True)
                raise UploadRejected(f"file size exceeds {settings.max_upload_bytes} bytes")
            out.write(chunk)

    if written == 0:
        target.unlink(missing_ok=True)
        raise UploadRejected("file is empty")
    return target
