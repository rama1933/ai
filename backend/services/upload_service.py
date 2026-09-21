import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from config import get_settings

READ_CHUNK = 64 * 1024
UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")

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


def classify(filename: str, content_type: str, head: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    rule = RULES.get(suffix)
    if rule is None:
        raise UploadRejected(f"extension {suffix!r} is not allowed; allowed: {sorted(RULES)}")

    kind, allowed_mimes, signatures = rule
    if content_type.split(";")[0].strip() not in allowed_mimes:
        raise UploadRejected(f"MIME type {content_type!r} does not match extension {suffix!r}")
    if signatures and not any(head.startswith(sig) for sig in signatures):
        raise UploadRejected(f"file signature does not match extension {suffix!r}")
    return kind


def _safe_name(filename: str) -> str:
    stem = Path(filename).name  # drops any directory traversal
    return UNSAFE_NAME_CHARS.sub("_", stem)


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
