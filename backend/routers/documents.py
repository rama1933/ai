from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import User
from schemas import IngestResponse
from security import get_current_user
from services.document_service import IngestError, ingest_file
from services import audit
from services.embedding_service import EmbeddingError
from services.upload_service import UploadRejected, save_upload

router = APIRouter(prefix="/documents", tags=["documents"])


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

    try:
        chunks = ingest_file(db, stored_path, user.id)
    except (IngestError, EmbeddingError) as exc:
        # No chunks means nothing references this file -- and an orphan would be
        # invisible to the knowledge screen while still counting toward storage_bytes.
        stored_path.unlink(missing_ok=True)
        if isinstance(exc, EmbeddingError):
            raise HTTPException(status_code=503, detail=f"local embedding model unavailable: {exc}") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit.record(db, audit.DOC_INGEST, user=user, target=stored_path.name, chunks=chunks)
    return IngestResponse(filename=stored_path.name, chunks=chunks)
