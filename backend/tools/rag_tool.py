import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from config import get_settings
from models import Document
from services.embedding_service import embed_query
from services.upload_service import display_name_of


# Province shorthand, spelled out into the query before it is embedded.
#
# Measured on the live corpus: "apa makanan khas kalsel" scored 0.5939 against the chunk
# holding the answer -- a hair under the 0.6 floor, so the turn answered "tidak
# ditemukan" -- while "makanan khas kalimantan selatan" scored 0.7799 against the same
# chunk. The corpus spells the names out (59 rows mention "Kalimantan Selatan") and
# almost never the shorthand (2 rows mention "kalsel"), so the abbreviation is the gap.
#
# Server-side and deterministic, like the file scope: this changes how a query is
# spelled, never which rows may be searched, and no model decides it. Provinces only --
# that shorthand is standard and unambiguous, while an agency acronym is not, so those
# wait for a measurement that says they are needed.
ABBREVIATIONS = {
    "kalsel": "kalimantan selatan",
    "kaltim": "kalimantan timur",
    "kalbar": "kalimantan barat",
    "kalteng": "kalimantan tengah",
    "kaltara": "kalimantan utara",
    "jabar": "jawa barat",
    "jateng": "jawa tengah",
    "jatim": "jawa timur",
    "dki": "jakarta",
    "diy": "yogyakarta",
    "sumut": "sumatera utara",
    "sumbar": "sumatera barat",
    "sumsel": "sumatera selatan",
    "babel": "bangka belitung",
    "kepri": "kepulauan riau",
    "ntb": "nusa tenggara barat",
    "ntt": "nusa tenggara timur",
    "sulsel": "sulawesi selatan",
    "sulteng": "sulawesi tengah",
    "sulut": "sulawesi utara",
    "sultra": "sulawesi tenggara",
    "malut": "maluku utara",
}

_TOKEN = re.compile(r"[a-z]+")


def _expanded(query: str) -> str:
    """The query with any province shorthand in it spelled out after the original words.

    Appended rather than substituted: what the user typed stays in the query. A shorthand
    whose expansion is already in the query is left alone -- repeating "kalimantan
    selatan" there only dilutes the words that were doing the work.
    """
    words = set(_TOKEN.findall(query.lower()))
    spelled = [
        full
        for short, full in ABBREVIATIONS.items()
        if short in words and not set(full.split()) <= words
    ]
    return f"{query} {' '.join(spelled)}" if spelled else query


# Words that mark a query as being about a file rather than about the world. A stem alone
# counts only with one of these: measured on the live corpus, "berapa jumlah provinsi di
# nusantara?" stepped on the word "nusantara" and scoped the search to nusantara.pdf --
# and a named scope does not widen, so the turn answered from a document the question never
# mentioned instead of from the corpus.
_FILE_MARKERS = frozenset({"file", "dokumen", "berkas", "doc"})


def _name_in_query(display: str, folded_query: str) -> bool:
    """True when the query quotes this document's name, with or without its extension.

    The whole name carries its own proof that a file is meant. A stem needs a marker word
    as well, and five characters: "ktp" is a subject, not a file name.
    """
    if display.casefold() in folded_query:
        return True
    stem = display.rsplit(".", 1)[0]
    return (
        len(stem) >= 5
        and stem.casefold() in folded_query
        and bool(set(_TOKEN.findall(folded_query)) & _FILE_MARKERS)
    )


def named_documents(db: Session | None, query: str) -> list[str]:
    """The stored filenames this query names, by the name the operator sees.

    Measured on the live corpus: 19 of 27 stored documents could not be reached by their
    own name -- asked "apa isi file policy.txt", the search came back empty. A chunk holds
    the document's content and its name lives in another column, so nothing was ever
    embedded for a name to match; the handful that did work were names that happened to
    share vocabulary with their own text.
    """
    if db is None:  # the callers that pass no session have nothing to look names up in
        return []
    folded = query.casefold()
    rows = db.query(Document.filename).distinct().order_by(Document.filename).all()
    quoted = {name: display_name_of(name) for (name,) in rows}
    exact = [name for name, display in quoted.items() if display.casefold() in folded]
    if exact:
        # Copies nest -- "X.pdf" sits inside "X__1_.pdf" and inside a uuid-prefixed copy of
        # either -- so a quoted name contained in a DIFFERENT quoted name is that other
        # document. A name that is merely shorter is its own document and stays: measured,
        # dropping every shorter name lost the second document of "policy.txt dan ktp.jpeg".
        # Identical names are the same document under several stored names, and each has to
        # stay: dropping them lost 10 of 28 rows in the by-name sweep.
        folded_names = {name: quoted[name].casefold() for name in exact}
        return [
            n
            for n in exact
            if not any(n != m and folded_names[n] != folded_names[m] and folded_names[n] in folded_names[m] for m in exact)
        ]
    return [name for name, display in quoted.items() if _name_in_query(display, folded)]


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
    vector = embed_query(_expanded(query))
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
