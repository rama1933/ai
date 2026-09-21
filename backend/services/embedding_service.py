import httpx

from config import get_settings

TIMEOUT_SECONDS = 120.0


class EmbeddingError(RuntimeError):
    """Ollama returned something we cannot use as an embedding."""


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    settings = get_settings()
    response = httpx.post(
        f"{settings.ollama_base_url}/api/embed",
        json={"model": settings.ollama_embedding_model, "input": texts},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise EmbeddingError(f"ollama /api/embed returned {response.status_code}: {response.text[:200]}")

    vectors = response.json().get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise EmbeddingError(f"expected {len(texts)} embeddings, got {vectors!r:.200}")

    expected_dim = settings.embedding_dim
    for vector in vectors:
        if len(vector) != expected_dim:
            raise EmbeddingError(
                f"embedding model returned dimension {len(vector)}, schema expects {expected_dim}"
            )
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
