import io


def test_upload_image_returns_stored_name(client):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    response = client.post("/upload", files={"file": ("struk.png", io.BytesIO(png), "image/png")})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "image"
    assert body["status"] == "stored"
    assert body["filename"].endswith("struk.png")


def test_upload_rejects_executable(client):
    response = client.post("/upload", files={"file": ("payload.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")})
    assert response.status_code == 400
    assert "extension" in response.json()["detail"]
