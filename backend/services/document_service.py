import re
from pathlib import Path

from sqlalchemy.orm import Session

from models import Document
from services.embedding_service import embed_texts

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
WHITESPACE = re.compile(r"\s+")


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


def ingest_file(db: Session, path: Path, user_id: int | None = None) -> int:
    """Load, clean, chunk, embed, and store a file. Returns the chunk count.

    user_id records provenance only. The corpus is shared by design, so retrieval
    ignores it; it exists so per-user filtering is a one-line change later rather
    than another migration.
    """
    text = clean_text(load_text(path))
    if not text:
        raise IngestError(f"{path.name} produced no extractable text")

    chunks = chunk_text(text)
    vectors = embed_texts(chunks)

    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        db.add(
            Document(
                filename=path.name,
                content=chunk,
                embedding=vector,
                user_id=user_id,
                doc_metadata={"chunk_index": index, "chunk_count": len(chunks), "source": str(path)},
            )
        )
    return len(chunks)
