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


def _vector2(a: float, b: float) -> list[float]:
    """Two non-parallel directions: cosine(a,b) < 1, so scores differ."""
    return [a, b] + [0.0] * 766


def test_rag_search_returns_nearest_chunks_first(db, monkeypatch):
    db.add(Document(filename="ragtest-a.txt", content="masa retensi dokumen 5 tahun", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="ragtest-b.txt", content="kebijakan arsip dan retensi dokumen", embedding=_vector2(1.0, 0.5), doc_metadata={}))
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


def test_rag_search_scopes_to_the_given_filenames(db, monkeypatch):
    """Session-scoped retrieval: the server narrows the search to its own
    attachments; a high-scoring chunk from another file must not leak in."""
    db.add(Document(filename="ragtest-a.txt", content="dokumen yang dimaksud", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="ragtest-b.txt", content="dokumen lain yang mirip", embedding=_vector(1.0), doc_metadata={}))
    db.flush()
    monkeypatch.setattr(rag_tool, "embed_query", lambda q: _vector(1.0))

    hits = rag_tool.rag_search(db, "dokumen", top_k=4, filenames=["ragtest-a.txt"])

    assert {h.filename for h in hits} == {"ragtest-a.txt"}


def test_rag_search_drops_hits_below_the_score_floor(db, monkeypatch):
    """Weak matches are how off-context answers start: below rag_min_score a hit
    is treated as no match, even when it is the nearest row."""
    db.add(Document(filename="ragtest-a.txt", content="hampir mirip", embedding=_vector2(0.5, 0.9), doc_metadata={}))
    db.add(Document(filename="ragtest-b.txt", content="benar-benar cocok", embedding=_vector(1.0), doc_metadata={}))
    db.flush()
    monkeypatch.setattr(rag_tool, "embed_query", lambda q: _vector(1.0))

    hits = rag_tool.rag_search(db, "apa saja", top_k=4)

    assert [h.filename for h in hits] == ["ragtest-b.txt"]


def test_rag_search_returns_empty_when_everything_is_below_the_floor(db, monkeypatch):
    """An empty result says 'tidak ditemukan' instead of feeding the model
    filler to summarise."""
    db.add(Document(filename="ragtest-a.txt", content="sama sekali tidak cocok", embedding=_vector(-1.0), doc_metadata={}))
    db.flush()
    monkeypatch.setattr(rag_tool, "embed_query", lambda q: _vector(1.0))

    assert rag_tool.rag_search(db, "apa saja", top_k=4) == []
