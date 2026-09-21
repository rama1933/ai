import io

import pytest
from fastapi import UploadFile

from services import upload_service


def _upload(name: str, content: bytes, content_type: str) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content), headers={"content-type": content_type})


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64


def test_classify_accepts_png_as_image():
    assert upload_service.classify("struk.png", "image/png", PNG) == "image"


def test_classify_accepts_pdf_as_document():
    assert upload_service.classify("policy.pdf", "application/pdf", PDF) == "document"


def test_classify_accepts_plain_text_document():
    assert upload_service.classify("policy.txt", "text/plain", b"kebijakan cuti") == "document"


def test_classify_rejects_disallowed_extension():
    with pytest.raises(upload_service.UploadRejected, match="extension"):
        upload_service.classify("payload.exe", "application/octet-stream", b"MZ\x90\x00")


def test_classify_rejects_mismatched_mime():
    with pytest.raises(upload_service.UploadRejected, match="MIME"):
        upload_service.classify("struk.png", "application/pdf", PNG)


def test_classify_rejects_forged_signature():
    # .png extension and image/png header, but the bytes are a PDF
    with pytest.raises(upload_service.UploadRejected, match="signature"):
        upload_service.classify("struk.png", "image/png", PDF)


def test_save_upload_rejects_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service.get_settings(), "max_upload_bytes", 32, raising=False)
    monkeypatch.setattr(upload_service.get_settings(), "upload_dir", tmp_path, raising=False)
    with pytest.raises(upload_service.UploadRejected, match="size"):
        upload_service.save_upload(_upload("big.png", PNG * 10, "image/png"), allowed_kinds={"image"})


def test_save_upload_rejects_wrong_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service.get_settings(), "upload_dir", tmp_path, raising=False)
    with pytest.raises(upload_service.UploadRejected, match="not accepted"):
        upload_service.save_upload(_upload("policy.pdf", PDF, "application/pdf"), allowed_kinds={"image"})


def test_save_upload_writes_sanitized_unique_name(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_service.get_settings(), "upload_dir", tmp_path, raising=False)
    path = upload_service.save_upload(_upload("../../etc/passwd.png", PNG, "image/png"), allowed_kinds={"image"})
    assert path.parent == tmp_path
    assert ".." not in path.name
    assert path.read_bytes() == PNG
