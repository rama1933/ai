import pytest

from tools import ocr_tool


def test_image_ocr_joins_recognized_lines(monkeypatch, tmp_path):
    image = tmp_path / "struk.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(ocr_tool.get_settings(), "upload_dir", tmp_path, raising=False)

    class FakeEngine:
        """Mirrors RapidOCR: engine(path) -> (lines, elapsed),
        where lines is [[box_points, text, confidence], ...]."""

        def __call__(self, path):
            return (
                [
                    [[[0, 0], [1, 0], [1, 1], [0, 1]], "TOKO MAJU", 0.99],
                    [[[0, 2], [1, 2], [1, 3], [0, 3]], "TOTAL 150000", 0.97],
                ],
                [0.11, 0.02],
            )

    monkeypatch.setattr(ocr_tool, "_engine", lambda: FakeEngine())

    assert ocr_tool.image_ocr(str(image)) == "TOKO MAJU\nTOTAL 150000"


def test_image_ocr_returns_empty_when_nothing_recognized(monkeypatch, tmp_path):
    image = tmp_path / "blank.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(ocr_tool.get_settings(), "upload_dir", tmp_path, raising=False)

    class EmptyEngine:
        def __call__(self, path):
            return (None, [0.01])

    monkeypatch.setattr(ocr_tool, "_engine", lambda: EmptyEngine())

    assert ocr_tool.image_ocr(str(image)) == ""


def test_image_ocr_rejects_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr_tool.get_settings(), "upload_dir", tmp_path, raising=False)
    with pytest.raises(ocr_tool.OcrError, match="not found"):
        ocr_tool.image_ocr(str(tmp_path / "struk.png"))


def test_image_ocr_rejects_path_outside_upload_dir(tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ocr_tool.OcrError, match="outside"):
        ocr_tool.image_ocr(str(outside))


def test_image_ocr_turns_a_decoder_failure_into_an_ocr_error(monkeypatch, tmp_path):
    """RapidOCR raises bare OSError/PIL errors on a file that is not an image, and the
    registry catches only OcrError. That mattered less when a model had to CHOOSE to call
    this tool; the orchestrator now reads every attached image before the model is asked,
    so an undecodable attachment reaches here on every turn it is carried and would
    otherwise take the whole turn down with it.
    """
    image = tmp_path / "truncated.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    monkeypatch.setattr(ocr_tool.get_settings(), "upload_dir", tmp_path, raising=False)

    class BrokenEngine:
        def __call__(self, path):
            raise OSError("Truncated File Read")

    monkeypatch.setattr(ocr_tool, "_engine", lambda: BrokenEngine())

    with pytest.raises(ocr_tool.OcrError, match="truncated.png"):
        ocr_tool.image_ocr(str(image))
