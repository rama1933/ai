from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from schemas import IngestResponse
from services.document_service import IngestError, ingest_file
from services.upload_service import UploadRejected, save_upload

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=IngestResponse)
def ingest_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> IngestResponse:
    try:
        stored_path: Path = save_upload(file, allowed_kinds={"document"})
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        chunks = ingest_file(db, stored_path)
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return IngestResponse(filename=stored_path.name, chunks=chunks)
