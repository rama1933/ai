import httpx
import pytest

from services import embedding_service


def test_embed_texts_posts_to_ollama_and_returns_vectors(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(
            200,
            json={"embeddings": [[0.1] * 768, [0.2] * 768]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(embedding_service.httpx, "post", fake_post)

    vectors = embedding_service.embed_texts(["satu", "dua"])

    assert captured["url"].endswith("/api/embed")
    assert captured["json"]["input"] == ["satu", "dua"]
    assert captured["json"]["model"] == "nomic-embed-text"
    assert len(vectors) == 2
    assert len(vectors[0]) == 768


def test_embed_texts_rejects_wrong_dimension(monkeypatch):
    def fake_post(url, json, timeout):
        return httpx.Response(200, json={"embeddings": [[0.1] * 384]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(embedding_service.httpx, "post", fake_post)

    with pytest.raises(embedding_service.EmbeddingError, match="768"):
        embedding_service.embed_texts(["satu"])


def test_embed_texts_returns_empty_for_empty_input(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("must not call ollama for empty input")

    monkeypatch.setattr(embedding_service.httpx, "post", explode)
    assert embedding_service.embed_texts([]) == []


@pytest.mark.integration
def test_embed_query_against_live_ollama():
    vector = embedding_service.embed_query("kebijakan cuti karyawan")
    assert len(vector) == 768
    assert any(v != 0 for v in vector)
