from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import UploadResponse
from security import get_current_user
from services import audit
from services.document_service import IngestError, ingest_file
from services.embedding_service import EmbeddingError
from services.upload_service import UploadRejected, display_name_of, save_upload, sniff

router = APIRouter(tags=["upload"])


@router.post("/upload", response_model=UploadResponse)
def upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UploadResponse:
    try:
        stored = save_upload(file, allowed_kinds={"image", "document"})
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with stored.open("rb") as handle:
        kind, mime = sniff(stored.name, handle.read(64))

    # One row for "this file is now on disk", in both branches: a document is also
    # ingested below, and that is the DOC_INGEST row.
    audit.record(db, audit.UPLOAD_STORE, user=user, target=stored.name, kind=kind, size=stored.stat().st_size)

    def response(status: str) -> UploadResponse:
        # filename keeps its documented meaning (the stored name); the richer
        # fields let the UI show a chip without ever trusting client metadata.
        return UploadResponse(
            filename=stored.name,
            status=status,
            kind=kind,
            stored_name=stored.name,
            display_name=display_name_of(stored.name),
            mime=mime,
            size=stored.stat().st_size,
        )

    if kind == "document":
        try:
            ingest_file(db, stored, user.id)
        except IngestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except EmbeddingError as exc:
            raise HTTPException(status_code=503, detail=f"local embedding model unavailable: {exc}") from exc
        return response("processed")

    # Images are not OCR'd here: the agent decides whether OCR is needed.
    return response("stored")
