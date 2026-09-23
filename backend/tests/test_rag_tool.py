import pytest

from database import SessionLocal
from models import Document
from tools import rag_tool


@pytest.fixture
def db():
    session = SessionLocal()
    session.query(Document).filter(Document.filename.like("%ragtest-%")).delete(synchronize_session=False)
    session.flush()
    yield session
    session.rollback()
    session.close()


def _vector(seed: float) -> list[float]:
    return [seed] + [0.0] * 767


def _vector2(a: float, b: float) -> list[float]:
    """Two non-parallel directions: cosine(a,b) < 1, so scores differ."""
    return [a, b] + [0.0] * 766


def _captured_query(monkeypatch) -> dict[str, str]:
    """What rag_search hands the embedding model, under "query"."""
    seen: dict[str, str] = {}

    def capture(query: str) -> list[float]:
        seen["query"] = query
        return _vector(1.0)

    monkeypatch.setattr(rag_tool, "embed_query", capture)
    return seen


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


def test_rag_search_returns_one_copy_of_a_chunk_stored_under_two_names(db, monkeypatch):
    """The same PDF uploaded three times filled all four slots with one passage, and a
    fresh URL ingest at rank #11 never reached the model. One copy, then the next
    distinct passage."""
    db.add(Document(filename="ragtest-a.pdf", content="jadwal interviu", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="ragtest-a-copy.pdf", content="jadwal interviu", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="ragtest-b.txt", content="tarif retribusi pasar", embedding=_vector2(1.0, 0.5), doc_metadata={}))
    db.flush()
    monkeypatch.setattr(rag_tool, "embed_query", lambda q: _vector(1.0))

    hits = rag_tool.rag_search(db, "apa saja", top_k=2)

    assert [h.content for h in hits] == ["jadwal interviu", "tarif retribusi pasar"]


def test_named_documents_finds_a_name_the_query_quotes(db):
    """Measured on the live corpus: 19 of 27 stored documents could not be reached by
    their own name -- asked "apa isi file policy.txt", the search returned nothing, because
    a chunk holds content while the name lives in another column."""
    db.add(Document(filename="ragtest-saya_adalah.txt", content="isi apa saja", embedding=_vector(1.0), doc_metadata={}))
    db.flush()

    assert rag_tool.named_documents(db, "apa isi file ragtest-saya_adalah.txt") == ["ragtest-saya_adalah.txt"]
    assert rag_tool.named_documents(db, "apa isi file RAGTEST-SAYA_ADALAH.txt") == ["ragtest-saya_adalah.txt"]
    assert rag_tool.named_documents(db, "berapa masa retensi dokumen?") == []


def test_named_documents_accepts_a_name_without_its_extension(db):
    db.add(Document(filename="ragtest-nusantara.pdf", content="isi apa saja", embedding=_vector(1.0), doc_metadata={}))
    db.flush()

    assert rag_tool.named_documents(db, "ringkas isi file ragtest-nusantara") == ["ragtest-nusantara.pdf"]


def test_named_documents_prefers_the_most_specific_name_the_query_quotes(db):
    """The corpus holds copies whose names contain each other -- a re-upload lands as
    "<uuid>-name.pdf" while "name.pdf" is still there, and the shorter name is a suffix of
    the longer one, so a question about the longer quotes both. Measured on the live corpus:
    asking for "2026kb6306267__1_.pdf" answered with "2026kb6306267.pdf"."""
    long_name = "ragtest-ragtest-2026kb.pdf"
    short_name = "ragtest-2026kb.pdf"
    db.add(Document(filename=long_name, content="isi panjang", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename=short_name, content="isi pendek", embedding=_vector(1.0), doc_metadata={}))
    db.flush()

    assert short_name in f"apa isi file {long_name}", "the shorter name is quoted too, or this proves nothing"
    assert rag_tool.named_documents(db, f"apa isi file {long_name}") == [long_name]


def test_named_documents_keeps_every_document_the_query_names(db):
    """Measured on the live corpus: "apa isi file policy.txt dan ktp.jpeg" came back with
    policy.txt alone, because the longest-name rule dropped every shorter name -- including
    ones the question actually asked for, and a named scope does not widen, so the corpus
    could not cover for it."""
    db.add(Document(filename="ragtest-policy.txt", content="kebijakan", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="ragtest-ktp.jpeg", content="ktp", embedding=_vector(1.0), doc_metadata={}))
    db.flush()

    assert rag_tool.named_documents(db, "apa isi file ragtest-policy.txt dan ragtest-ktp.jpeg") == [
        "ragtest-ktp.jpeg",
        "ragtest-policy.txt",
    ]


def test_named_documents_keeps_every_copy_of_a_quoted_name(db):
    """The corpus holds one document under several uuid-prefixed names, so a single quoted
    name matches several rows that all display the same. Dropping a name because an
    identical one is also quoted loses the document entirely -- measured, the by-name sweep
    over the live corpus fell from 25 of 28 stored rows to 15."""
    db.add(Document(filename="a" * 32 + "-ragtest-ktp.jpeg", content="a", embedding=_vector(1.0), doc_metadata={}))
    db.add(Document(filename="b" * 32 + "-ragtest-ktp.jpeg", content="b", embedding=_vector(1.0), doc_metadata={}))
    db.flush()

    assert rag_tool.named_documents(db, "apa isi file ragtest-ktp.jpeg") == [
        "a" * 32 + "-ragtest-ktp.jpeg",
        "b" * 32 + "-ragtest-ktp.jpeg",
    ]


def test_a_bare_word_that_matches_a_file_stem_does_not_scope_a_search():
    """Measured on the live corpus: "berapa jumlah provinsi di nusantara?" stepped on the
    word "nusantara", scoped the search to nusantara.pdf, and -- a named scope not widening
    -- the turn answered from a document the question never mentioned. A stem counts only
    when the query says it is asking about a file."""
    assert not rag_tool._name_in_query("nusantara.pdf", "berapa jumlah provinsi di nusantara?")
    assert rag_tool._name_in_query("nusantara.pdf", "apa isi file nusantara")
    assert rag_tool._name_in_query("nusantara.pdf", "ringkas dokumen nusantara")


def test_a_stem_too_short_to_be_a_name_does_not_scope_a_search():
    """A guard, and green when it was written: "ktp" is a subject, not a file name, and
    scoping to a three-letter stem would narrow questions that never named anything."""
    assert rag_tool._name_in_query("ktp.jpeg", "apa isi file ktp.jpeg"), "the whole name still counts"
    assert not rag_tool._name_in_query("ktp.jpeg", "apa syarat membuat ktp")
    assert not rag_tool._name_in_query("ktp.jpeg", "apa isi file ktp"), "a marker does not rescue three letters"
    assert rag_tool._name_in_query("policy.txt", "bagaimana isi file policy itu")


def test_rag_search_expands_a_province_abbreviation_before_embedding(db, monkeypatch):
    """Measured on the live corpus: "apa makanan khas kalsel" scored 0.5939 against the
    chunk holding the answer -- a hair under the 0.6 floor, so the turn answered "tidak
    ditemukan" -- while "makanan khas kalimantan selatan" scored 0.7799 against the same
    chunk. The corpus spells the name out (59 rows) and almost never the shorthand (2).
    """
    seen = _captured_query(monkeypatch)

    rag_tool.rag_search(db, "apa makanan khas kalsel")

    assert "kalimantan selatan" in seen["query"]
    assert "kalsel" in seen["query"], "the words the user chose are kept, not replaced"


def test_rag_search_embeds_a_query_with_no_abbreviation_unchanged(db, monkeypatch):
    """A guard, and green when it was written: only the shorthand table may rewrite a
    query, so ordinary phrasing has to reach the embedding model exactly as typed."""
    seen = _captured_query(monkeypatch)

    rag_tool.rag_search(db, "berapa masa retensi dokumen keuangan?")

    assert seen["query"] == "berapa masa retensi dokumen keuangan?"


def test_rag_search_does_not_expand_an_abbreviation_the_query_already_spells_out(db, monkeypatch):
    """A guard, and green when it was written: repeating "kalimantan selatan" in a query
    that already carries it only dilutes the words that were doing the work."""
    seen = _captured_query(monkeypatch)

    rag_tool.rag_search(db, "makanan khas kalsel kalimantan selatan")

    assert seen["query"] == "makanan khas kalsel kalimantan selatan"
