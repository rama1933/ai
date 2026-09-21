import pytest

from database import SessionLocal
from models import Document
from tools import rag_tool


@pytest.fixture
def db():
    session = SessionLocal()
    session.query(Document).filter(Document.filename.like("ragtest-%")).delete(synchronize_session=False)
    session.flush()
    yield session
    session.rollback()
    session.close()


def _vector(seed: float) -> list[float]:
    return [seed] + [0.0] * 767


def test_rag_search_returns_nearest_chunks_first(db, monkeypatch):
    db.add(Document(filename="ragtest-a.txt", content="masa retensi dokumen 5 tahun", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="ragtest-b.txt", content="menu makan siang kantin", embedding=_vector(-1.0), doc_metadata={}))
    db.flush()

    monkeypatch.setattr(rag_tool, "embed_query", lambda q: _vector(1.0))

    hits = rag_tool.rag_search(db, "berapa lama masa retensi dokumen?", top_k=2)

    assert hits[0].filename == "ragtest-a.txt"
    assert hits[0].score > hits[1].score
    assert 0.0 <= hits[0].score <= 1.0


def test_rag_search_respects_top_k(db, monkeypatch):
    for i in range(5):
        db.add(Document(filename=f"ragtest-{i}.txt", content=f"isi {i}", embedding=_vector(1.0), doc_metadata={}))
    db.flush()
    monkeypatch.setattr(rag_tool, "embed_query", lambda q: _vector(1.0))

    assert len(rag_tool.rag_search(db, "apa saja", top_k=3)) == 3


def test_rag_search_returns_empty_when_no_documents(db, monkeypatch):
    monkeypatch.setattr(rag_tool, "embed_query", lambda q: _vector(1.0))
    db.query(Document).delete(synchronize_session=False)
    db.flush()
    assert rag_tool.rag_search(db, "apa saja") == []
