import pytest

from agent import registry
from tools.rag_tool import RagHit


def test_tool_schemas_expose_three_tools():
    names = {schema["function"]["name"] for schema in registry.TOOL_SCHEMAS}
    assert names == {"rag_search", "image_ocr", "sql_query"}
    for schema in registry.TOOL_SCHEMAS:
        assert schema["type"] == "function"
        assert schema["function"]["parameters"]["type"] == "object"


def test_dispatch_rag_search_wraps_results_as_untrusted(monkeypatch):
    monkeypatch.setattr(
        registry, "rag_search",
        lambda db, query, top_k=4, filenames=None: [RagHit(filename="policy.pdf", content="retensi 5 tahun", score=0.91)],
    )
    outcome = registry.dispatch("rag_search", {"query": "retensi"}, db=None, image_paths=[])

    assert registry.UNTRUSTED_HEADER in outcome.text
    assert "retensi 5 tahun" in outcome.text
    assert outcome.sources[0].filename == "policy.pdf"
    assert outcome.sources[0].score == 0.91


def test_dispatch_rag_search_reports_no_match(monkeypatch):
    monkeypatch.setattr(registry, "rag_search", lambda db, query, top_k=4, filenames=None: [])
    outcome = registry.dispatch("rag_search", {"query": "apa pun"}, db=None, image_paths=[])
    assert "tidak ditemukan" in outcome.text.lower() or "no matching" in outcome.text.lower()
    assert outcome.sources == []


def test_dispatch_image_ocr_uses_session_image_not_model_supplied_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(registry, "image_ocr", lambda path: seen.update(path=path) or "TOTAL 150000")

    outcome = registry.dispatch(
        "image_ocr", {"image_path": "/etc/passwd"}, db=None, image_paths=["/uploads/abc-struk.png"]
    )

    assert seen["path"] == "/uploads/abc-struk.png"
    assert "TOTAL 150000" in outcome.text


def test_dispatch_image_ocr_without_uploaded_image_is_an_error_message(monkeypatch):
    outcome = registry.dispatch("image_ocr", {}, db=None, image_paths=[])
    assert "no image" in outcome.text.lower()
    # grounded=False as well: the text reads like a helpful sentence, so without the
    # flag the orchestrator counted the turn as having read something.
    assert outcome.grounded is False


def test_dispatch_sql_query_returns_rejection_as_text_not_exception(monkeypatch):
    from tools.sql_tool import SqlRejected

    def reject(query, max_rows=50):
        raise SqlRejected("table 'users' is not allowed")

    monkeypatch.setattr(registry, "sql_query", reject)
    outcome = registry.dispatch("sql_query", {"query": "SELECT * FROM users"}, db=None, image_paths=[])

    assert "not allowed" in outcome.text
    assert outcome.sources == []


def test_dispatch_unknown_tool_returns_error_text():
    outcome = registry.dispatch("rm_rf", {}, db=None, image_paths=[])
    assert "unknown tool" in outcome.text.lower()


def test_dispatch_scopes_rag_search_to_session_documents(monkeypatch):
    """document_filenames rides in from the session like image_paths does for
    OCR -- server-derived, never chosen by the model. When the model's query is
    too weak to clear the floor against those files, the opening chunks step in
    so a summary request still gets the document's title and subject."""
    seen = {}
    monkeypatch.setattr(
        registry, "rag_search", lambda db, query, top_k=4, filenames=None: seen.update(
            query=query, top_k=top_k, filenames=filenames
        ) or []
    )
    fallback = {}
    monkeypatch.setattr(
        registry, "first_chunks", lambda db, filenames, limit=4: fallback.update(
            filenames=filenames, limit=limit
        ) or [RagHit(filename="abc-laporan.pdf", content="KEPUTUSAN BUPATI TENTANG REDISTRIBUSI TANAH", score=1.0)]
    )

    outcome = registry.dispatch(
        "rag_search", {"query": "pelajari dokumen ini"}, db=None,
        image_paths=[], document_filenames=["abc-laporan.pdf"],
    )

    assert seen["filenames"] == ["abc-laporan.pdf"]
    assert seen["top_k"] == 6  # scoped reads go a little deeper
    assert fallback["filenames"] == ["abc-laporan.pdf"]
    assert "KEPUTUSAN BUPATI" in outcome.text  # the opening chunk reached the model


def test_dispatch_rag_search_without_session_documents_stays_global(monkeypatch):
    """No session documents, no scoping and no fallback: plain global search."""
    seen = {}
    monkeypatch.setattr(
        registry, "rag_search",
        lambda db, query, top_k=4, filenames=None: seen.update(top_k=top_k, filenames=filenames) or [
            RagHit(filename="policy.pdf", content="retensi 5 tahun", score=0.9)
        ],
    )
    monkeypatch.setattr(
        registry, "first_chunks",
        lambda db, filenames, limit=4: (_ for _ in ()).throw(AssertionError("fallback must not run")),
    )

    outcome = registry.dispatch("rag_search", {"query": "masa retensi"}, db=None, image_paths=[])

    assert seen["top_k"] == 4
    assert seen["filenames"] is None
    assert "retensi 5 tahun" in outcome.text


def test_image_ocr_keeps_the_extract_as_the_corpus_for_that_image(monkeypatch):
    """An image is readable only while it is attached -- the orchestrator hands OCR the
    paths of THIS message -- so the text has to outlive the turn.

    Measured live without this: turn 1 answered "Rp 43.000" from the receipt, and the
    next turn ("sebutkan lagi totalnya berapa?"), which carried no image, refused.

    Stored under the STORED name rather than the display name: the session's scope is
    rebuilt from chat_history.attachments[].stored_name, and two uploads of the same
    picture share a display name but never a stored one.
    """
    kept = []

    class FakeSession:
        """Only commit is reached: the extract has to survive a turn with no answer,
        so _keep_extract commits it on its own rather than with the answer."""

        def __init__(self):
            self.commits = 0

        def commit(self):
            self.commits += 1

    session = FakeSession()
    monkeypatch.setattr(registry, "image_ocr", lambda path: "TOKO MAJU JAYA TOTAL 43000")
    monkeypatch.setattr(
        registry,
        "ingest_extract",
        lambda db, text, filename, user_id=None, source=None: kept.append((text, filename, source)) or 1,
    )

    outcome = registry.dispatch("image_ocr", {}, db=session, image_paths=["/uploads/abc-struk.png"])

    assert kept == [("TOKO MAJU JAYA TOTAL 43000", "abc-struk.png", "/uploads/abc-struk.png")]
    assert session.commits == 1
    assert outcome.grounded is True
    assert [s.filename for s in outcome.sources] == ["abc-struk.png"]


def test_a_failed_extract_save_does_not_cost_the_answer(monkeypatch):
    """What the user asked for is the answer. A local embedding outage must not turn a
    readable image into a refusal, so the save is best effort and the OCR text in hand
    still grounds the turn."""
    from services.embedding_service import EmbeddingError

    monkeypatch.setattr(registry, "image_ocr", lambda path: "TOTAL 43000")

    def refused(*args, **kwargs):
        raise EmbeddingError("cannot reach the embedding model")

    monkeypatch.setattr(registry, "ingest_extract", refused)

    outcome = registry.dispatch("image_ocr", {}, db="a-session", image_paths=["/uploads/abc-struk.png"])

    assert "43000" in outcome.text
    assert outcome.grounded is True
