from dataclasses import dataclass

from sqlalchemy.orm import Session

from config import get_settings
from models import Document
from services.embedding_service import embed_query


@dataclass(frozen=True)
class RagHit:
    filename: str
    content: str
    score: float


def rag_search(
    db: Session,
    query: str,
    top_k: int = 4,
    filenames: list[str] | None = None,
) -> list[RagHit]:
    """Cosine similarity search over the documents table.

    The index in db/schema.sql is vector_cosine_ops, so cosine_distance is the
    operator that can actually use it. score = 1 - distance.

    `filenames` scopes the search to those files. It is supplied by the server
    from the session's own attachments -- the model never names a file; the tool
    schema exposes only `query`. Hits below `rag_min_score` are dropped: weak
    matches are how off-context answers start, and an empty result tells the
    model "tidak ditemukan" instead of feeding it filler to summarise.
    """
    vector = embed_query(query)
    distance = Document.embedding.cosine_distance(vector).label("distance")

    query_ = db.query(Document.filename, Document.content, distance)
    if filenames:
        query_ = query_.filter(Document.filename.in_(filenames))
    # Over-fetch so the score floor and the dedupe below cannot silently hand back
    # fewer than the documents that actually clear it.
    # ponytail: 5x, kept under pgvector's default hnsw.ef_search of 40 -- an HNSW
    # scan returns at most that many rows. Raise ef_search with the multiplier if
    # top_k ever grows past 8.
    rows = query_.order_by(distance).limit(top_k * 5).all()

    # One copy per passage: the same file uploaded three times filled every slot
    # with one chunk (193 of 263 distinct chunks sit under more than one name).
    min_score = get_settings().rag_min_score
    hits: list[RagHit] = []
    seen: set[str] = set()
    for filename, content, dist in rows:
        score = round(1.0 - float(dist), 4)
        if score >= min_score and content not in seen:
            seen.add(content)
            hits.append(RagHit(filename=filename, content=content, score=score))
    return hits[:top_k]


def first_chunks(db: Session, filenames: list[str], limit: int = 4) -> list[RagHit]:
    """The opening chunks of the given documents, in stored order.

    Deterministic fallback for scoped retrieval: a vague question ("pelajari
    dokumen ini") can embed too weakly to clear the score floor against any
    chunk, but a document's first chunks carry its title and subject line --
    exactly the context summarising needs. No score filtering: the intent is
    coverage of these files, not similarity.
    """
    if not filenames:
        return []
    rows = (
        db.query(Document.filename, Document.content)
        .filter(Document.filename.in_(filenames))
        .order_by(Document.id.asc())
        .limit(limit)
        .all()
    )
    return [RagHit(filename=filename, content=content, score=1.0) for filename, content in rows]
