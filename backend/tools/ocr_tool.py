from functools import lru_cache
from pathlib import Path

from config import get_settings


class OcrError(RuntimeError):
    """The image could not be read."""


@lru_cache
def _engine():
    """RapidOCR builds its ONNX sessions on first construction (~seconds), so build once."""
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def image_ocr(image_path: str) -> str:
    """Extract text from an uploaded image. Returns "" when nothing is recognized."""
    upload_dir = Path(get_settings().upload_dir).resolve()
    path = Path(image_path).resolve()

    if not path.is_relative_to(upload_dir):
        raise OcrError(f"refusing to read {image_path!r}: outside the upload directory")
    if not path.is_file():
        raise OcrError(f"image not found: {image_path}")

    try:
        raw = _engine()(str(path))
    except Exception as exc:  # noqa: BLE001 - RapidOCR raises bare OSError on a non-image
        # Any read failure is this tool's failure, not the caller's. An undecodable
        # attachment reaches here on EVERY turn it is carried: the orchestrator reads
        # attachments before the model is asked, so this is no longer a path only a
        # tool-choosing model can take. Measured: a 72-byte fake PNG made POST /chat a
        # 500, because RapidOCR's OSError("Truncated File Read") is not an OcrError and
        # registry.dispatch catches only OcrError. Both callers already handle OcrError.
        raise OcrError(f"could not read {path.name}: {exc}") from exc
    # RapidOCR returns (lines, elapsed); lines is [[box_points, text, confidence], ...] or None.
    lines = raw[0] if isinstance(raw, tuple) else raw
    if not lines:
        return ""
    return "\n".join(line[1] for line in lines)
