from dataclasses import dataclass

from sqlalchemy.orm import Session

from models import Document
from services.embedding_service import embed_query


@dataclass(frozen=True)
class RagHit:
    filename: str
    content: str
    score: float


def rag_search(db: Session, query: str, top_k: int = 4) -> list[RagHit]:
    """Cosine similarity search over the documents table.

    The index in db/schema.sql is vector_cosine_ops, so cosine_distance is the
    operator that can actually use it. score = 1 - distance.
    """
    vector = embed_query(query)
    distance = Document.embedding.cosine_distance(vector).label("distance")

    rows = (
        db.query(Document.filename, Document.content, distance)
        .order_by(distance)
        .limit(top_k)
        .all()
    )
    return [
        RagHit(filename=filename, content=content, score=round(1.0 - float(dist), 4))
        for filename, content, dist in rows
    ]
