from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import UploadResponse
from security import get_current_user
from services.document_service import IngestError, ingest_file
from services.upload_service import UploadRejected, classify, save_upload

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
        kind = classify(stored.name, file.content_type or "", handle.read(64))
    if kind == "document":
        try:
            ingest_file(db, stored)
        except IngestError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return UploadResponse(filename=stored.name, status="processed", kind=kind)

    # Images are not OCR'd here: the agent decides whether OCR is needed.
    return UploadResponse(filename=stored.name, status="stored", kind=kind)
