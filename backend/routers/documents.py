from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import IngestResponse, IngestTextRequest, IngestUrlRequest
from security import get_current_user, require_role
from services import audit
from services.document_service import IngestError, fetch_url_text, ingest_file, name_from_url
from services.embedding_service import EmbeddingError
from services.upload_service import UploadRejected, save_upload, store_text_file

router = APIRouter(prefix="/documents", tags=["documents"])

# Only /url uses this. The file and text routes stay open to any signed-in user --
# they only store what the caller already has, and /auth/register is open, so
# anything stricter there would be a lock on an empty room. /url is different: it
# makes this server issue a request to an address the caller chose. See fetch_url_text.
ADMIN_ONLY = require_role("ADMIN")


def _ingest_stored(db: Session, stored_path: Path, user: User) -> int:
    """Chunk, embed and audit one stored file -- or remove it and say why not.

    No chunks means nothing references this file, and an orphan would be invisible
    to the knowledge screen while still counting toward storage_bytes.
    """
    try:
        chunks = ingest_file(db, stored_path, user.id)
    except (IngestError, EmbeddingError) as exc:
        stored_path.unlink(missing_ok=True)
        if isinstance(exc, EmbeddingError):
            raise HTTPException(status_code=503, detail=f"local embedding model unavailable: {exc}") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit.record(db, audit.DOC_INGEST, user=user, target=stored_path.name, chunks=chunks)
    return chunks


@router.post("", response_model=IngestResponse)
def ingest_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestResponse:
    try:
        stored_path: Path = save_upload(file, allowed_kinds={"document"})
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IngestResponse(filename=stored_path.name, chunks=_ingest_stored(db, stored_path, user))


@router.post("/text", response_model=IngestResponse)
def ingest_text(
    payload: IngestTextRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestResponse:
    """Pasted text, written out as a file so it is a document like any other."""
    try:
        stored_path = store_text_file(payload.content, payload.title or "catatan")
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IngestResponse(filename=stored_path.name, chunks=_ingest_stored(db, stored_path, user))


@router.post("/url", response_model=IngestResponse)
def ingest_url(
    payload: IngestUrlRequest,
    db: Session = Depends(get_db),
    user: User = Depends(ADMIN_ONLY),
) -> IngestResponse:
    """One web page. The backend fetches it (see fetch_url_text) and stores the text
    it read, not the URL: retrieval stays a lookup over the corpus, so a page that
    changes or disappears later cannot silently change what the assistant answers.

    Admin-only, and not for tidiness: this is the one ingest path where the caller
    picks an address for the server itself to open. On a route any registered user
    can reach, http://127.0.0.1:8000/... or a cloud metadata address would be a
    read primitive, and the page it returns lands in the shared corpus, which
    /chat and the SQL tool can then quote back."""
    try:
        text = fetch_url_text(payload.url)
        stored_path = store_text_file(text, payload.title or name_from_url(payload.url))
    except (IngestError, UploadRejected) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return IngestResponse(filename=stored_path.name, chunks=_ingest_stored(db, stored_path, user))
