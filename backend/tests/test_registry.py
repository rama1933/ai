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


def test_dispatch_lets_a_stronger_corpus_hit_into_a_scoped_search(monkeypatch):
    """A session that once carried a PDF could never reach knowledge added later:
    measured live, the new note scored 0.86 unscoped while the scoped search returned
    six chunks of the old PDF at 0.72 -- above the floor, so the turn looked grounded.
    A corpus hit that beats the best session hit comes in; a weaker one and a second
    copy of a session passage do not."""
    def fake_rag(db, query, top_k=4, filenames=None):
        if filenames:
            return [RagHit(filename="abc-jadwal.pdf", content="jadwal interviu", score=0.72)]
        return [
            RagHit(filename="new-ktp.txt", content="pelayanan KTP hari Selasa", score=0.86),
            RagHit(filename="copy-jadwal.pdf", content="jadwal interviu", score=0.72),
            RagHit(filename="old.txt", content="makanan khas", score=0.65),
        ]

    monkeypatch.setattr(registry, "rag_search", fake_rag)

    outcome = registry.dispatch(
        "rag_search", {"query": "jadwal KTP"}, db=None,
        image_paths=[], document_filenames=["abc-jadwal.pdf"],
    )

    assert [s.filename for s in outcome.sources] == ["new-ktp.txt", "abc-jadwal.pdf"]


def test_dispatch_without_widen_keeps_a_scoped_search_to_its_files(monkeypatch):
    """The turn that attaches a file reads that file only -- see
    test_read_first_reads_what_this_message_attached_not_the_whole_session."""
    calls = []

    def fake_rag(db, query, top_k=4, filenames=None):
        calls.append(filenames)
        return [RagHit(filename="abc-jadwal.pdf", content="jadwal interviu", score=0.72)]

    monkeypatch.setattr(registry, "rag_search", fake_rag)

    registry.dispatch(
        "rag_search", {"query": "jadwal"}, db=None,
        image_paths=[], document_filenames=["abc-jadwal.pdf"], widen=False,
    )

    assert calls == [["abc-jadwal.pdf"]]


def test_dispatch_first_chunks_fallback_does_not_widen(monkeypatch):
    """A vague "pelajari dokumen ini" that clears the floor against nothing anchors to
    the session's opening chunks; the corpus is not searched, so a stray 0.65 chunk
    from another file cannot take the summary over."""
    calls = []

    def fake_rag(db, query, top_k=4, filenames=None):
        calls.append(filenames)
        return []

    monkeypatch.setattr(registry, "rag_search", fake_rag)
    monkeypatch.setattr(
        registry, "first_chunks",
        lambda db, filenames, limit=4: [RagHit(filename="abc-laporan.pdf", content="KEPUTUSAN BUPATI", score=1.0)],
    )

    outcome = registry.dispatch(
        "rag_search", {"query": "pelajari dokumen ini"}, db=None,
        image_paths=[], document_filenames=["abc-laporan.pdf"],
    )

    assert calls == [["abc-laporan.pdf"]]
    assert [s.filename for s in outcome.sources] == ["abc-laporan.pdf"]


def test_dispatch_scopes_to_the_document_the_query_names(monkeypatch):
    """The model names no file -- but the user does, in the question. Measured, most stored
    documents could not be reached by their own name at all: the name is not part of what
    was embedded, so a search has nothing to match it against."""
    seen = {}
    monkeypatch.setattr(
        registry, "rag_search",
        lambda db, query, top_k=4, filenames=None: seen.update(filenames=filenames, top_k=top_k)
        or [RagHit(filename="abc-laporan.pdf", content="isi laporan", score=0.8)],
    )
    monkeypatch.setattr(registry, "named_documents", lambda db, query: ["abc-laporan.pdf"])

    outcome = registry.dispatch("rag_search", {"query": "apa isi file abc-laporan.pdf"}, db=None, image_paths=[])

    assert seen["filenames"] == ["abc-laporan.pdf"]
    assert [s.filename for s in outcome.sources] == ["abc-laporan.pdf"]


def test_dispatch_does_not_widen_a_search_the_query_narrowed(monkeypatch):
    """Naming a document asks about that document, so the corpus must not be pulled back in
    around it -- the same rule the file this message attached already gets."""
    calls = []
    monkeypatch.setattr(
        registry, "rag_search",
        lambda db, query, top_k=4, filenames=None: calls.append(filenames)
        or [RagHit(filename="abc-laporan.pdf", content="isi laporan", score=0.72)],
    )
    monkeypatch.setattr(registry, "named_documents", lambda db, query: ["abc-laporan.pdf"])

    registry.dispatch("rag_search", {"query": "apa isi file abc-laporan.pdf"}, db=None, image_paths=[])

    assert calls == [["abc-laporan.pdf"]]


def test_dispatch_lets_the_session_scope_win_over_a_named_document(monkeypatch):
    """A guard, and green when it was written: read-first reads the session's own files, and
    that scope is server-derived -- a name in the query must not displace it."""
    calls = []
    monkeypatch.setattr(
        registry, "rag_search",
        lambda db, query, top_k=4, filenames=None: calls.append(filenames)
        or [RagHit(filename="session.pdf", content="isi sesi", score=0.8)],
    )
    monkeypatch.setattr(
        registry, "named_documents",
        lambda db, query: (_ for _ in ()).throw(AssertionError("the session scope decides")),
    )

    registry.dispatch(
        "rag_search", {"query": "apa isi file lain.pdf"}, db=None,
        image_paths=[], document_filenames=["session.pdf"],
    )

    # The scoped call, not the widening one that follows it -- that one is unscoped by design.
    assert calls[0] == ["session.pdf"]


def test_dispatch_reaches_the_corpus_when_the_session_scope_has_nothing_left(monkeypatch):
    """A session whose attachment was deleted from the knowledge page still names it in
    chat_history, so the scoped search and its first_chunks fallback both come back empty
    -- and every later turn of that session was refused for good, with the answer sitting
    in the corpus. Reachable through the console's own delete button."""
    calls = []

    def fake_rag(db, query, top_k=4, filenames=None):
        calls.append(filenames)
        return [] if filenames else [RagHit(filename="new-ktp.txt", content="pelayanan KTP hari Selasa", score=0.86)]

    monkeypatch.setattr(registry, "rag_search", fake_rag)
    monkeypatch.setattr(registry, "first_chunks", lambda db, filenames, limit=4: [])

    outcome = registry.dispatch(
        "rag_search", {"query": "jadwal KTP"}, db=None,
        image_paths=[], document_filenames=["deleted.pdf"],
    )

    assert calls == [["deleted.pdf"], None]
    assert [s.filename for s in outcome.sources] == ["new-ktp.txt"]


def test_dispatch_without_widen_keeps_a_dead_scope_dead(monkeypatch):
    """The turn that attaches a file reads only that file, even when its scope is empty:
    widening there is how a receipt answered a question about a freshly attached PDF."""
    calls = []

    def fake_rag(db, query, top_k=4, filenames=None):
        calls.append(filenames)
        return [] if filenames else [RagHit(filename="new-ktp.txt", content="pelayanan KTP hari Selasa", score=0.86)]

    monkeypatch.setattr(registry, "rag_search", fake_rag)
    monkeypatch.setattr(registry, "first_chunks", lambda db, filenames, limit=4: [])

    outcome = registry.dispatch(
        "rag_search", {"query": "jadwal KTP"}, db=None,
        image_paths=[], document_filenames=["deleted.pdf"], widen=False,
    )

    assert calls == [["deleted.pdf"]]
    assert outcome.grounded is False


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
