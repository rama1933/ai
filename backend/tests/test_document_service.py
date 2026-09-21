from pathlib import Path

import pytest

from database import SessionLocal
from models import Document
from services import document_service


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


def test_clean_text_collapses_whitespace_and_strips_control_chars():
    raw = "Kebijakan\x00  cuti\n\n\n   karyawan \t adalah  12 hari."
    assert document_service.clean_text(raw) == "Kebijakan cuti karyawan adalah 12 hari."


def test_chunk_text_respects_size_and_overlap():
    text = " ".join(f"kata{i}" for i in range(400))
    chunks = document_service.chunk_text(text, size=200, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    # consecutive chunks share text, so nothing falls between the cracks
    assert chunks[0][-20:] in chunks[1]


def test_chunk_text_returns_single_chunk_for_short_text():
    assert document_service.chunk_text("pendek saja", size=200, overlap=50) == ["pendek saja"]


def test_load_text_reads_txt(tmp_path: Path):
    target = tmp_path / "policy.txt"
    target.write_text("isi kebijakan", encoding="utf-8")
    assert document_service.load_text(target) == "isi kebijakan"


def test_load_text_rejects_unsupported_extension(tmp_path: Path):
    target = tmp_path / "policy.docx"
    target.write_bytes(b"whatever")
    with pytest.raises(document_service.IngestError, match="unsupported"):
        document_service.load_text(target)


def test_ingest_file_stores_one_row_per_chunk(tmp_path: Path, db, monkeypatch):
    monkeypatch.setattr(
        document_service, "embed_texts", lambda texts: [[0.01] * 768 for _ in texts]
    )
    target = tmp_path / "unit-policy.txt"
    target.write_text(" ".join(f"kata{i}" for i in range(500)), encoding="utf-8")

    stored = document_service.ingest_file(db, target)
    db.flush()

    rows = db.query(Document).filter_by(filename="unit-policy.txt").all()
    assert stored == len(rows) > 1
    assert rows[0].doc_metadata["chunk_index"] == 0
