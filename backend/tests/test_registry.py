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
        lambda db, query, top_k=4: [RagHit(filename="policy.pdf", content="retensi 5 tahun", score=0.91)],
    )
    outcome = registry.dispatch("rag_search", {"query": "retensi"}, db=None, image_path=None)

    assert registry.UNTRUSTED_HEADER in outcome.text
    assert "retensi 5 tahun" in outcome.text
    assert outcome.sources[0].filename == "policy.pdf"
    assert outcome.sources[0].score == 0.91


def test_dispatch_rag_search_reports_no_match(monkeypatch):
    monkeypatch.setattr(registry, "rag_search", lambda db, query, top_k=4: [])
    outcome = registry.dispatch("rag_search", {"query": "apa pun"}, db=None, image_path=None)
    assert "tidak ditemukan" in outcome.text.lower() or "no matching" in outcome.text.lower()
    assert outcome.sources == []


def test_dispatch_image_ocr_uses_session_image_not_model_supplied_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(registry, "image_ocr", lambda path: seen.update(path=path) or "TOTAL 150000")

    outcome = registry.dispatch(
        "image_ocr", {"image_path": "/etc/passwd"}, db=None, image_path="/uploads/abc-struk.png"
    )

    assert seen["path"] == "/uploads/abc-struk.png"
    assert "TOTAL 150000" in outcome.text


def test_dispatch_image_ocr_without_uploaded_image_is_an_error_message(monkeypatch):
    outcome = registry.dispatch("image_ocr", {}, db=None, image_path=None)
    assert "no image" in outcome.text.lower()


def test_dispatch_sql_query_returns_rejection_as_text_not_exception(monkeypatch):
    from tools.sql_tool import SqlRejected

    def reject(query, max_rows=50):
        raise SqlRejected("table 'users' is not allowed")

    monkeypatch.setattr(registry, "sql_query", reject)
    outcome = registry.dispatch("sql_query", {"query": "SELECT * FROM users"}, db=None, image_path=None)

    assert "not allowed" in outcome.text
    assert outcome.sources == []


def test_dispatch_unknown_tool_returns_error_text():
    outcome = registry.dispatch("rm_rf", {}, db=None, image_path=None)
    assert "unknown tool" in outcome.text.lower()
