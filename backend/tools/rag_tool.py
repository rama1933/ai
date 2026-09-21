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
    # Over-fetch so the score floor cannot silently hand back fewer than the
    # documents that actually clear it.
    rows = query_.order_by(distance).limit(top_k * 3).all()

    min_score = get_settings().rag_min_score
    hits = [
        RagHit(filename=filename, content=content, score=round(1.0 - float(dist), 4))
        for filename, content, dist in rows
        if 1.0 - float(dist) >= min_score
    ]
    return hits[:top_k]
