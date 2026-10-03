"""/ocr エンドポイント。PaddleOCR 呼び出し（run_ocr）はスタブ化し、
抽出ロジック＋レスポンス整形を検証する。"""

import io
from PIL import Image
import pytest

_buffer = io.BytesIO()
Image.new("RGB", (20, 20)).save(_buffer, format="JPEG")
IMAGE_BYTES = _buffer.getvalue()
from httpx import ASGITransport, AsyncClient

import app.main as ocr_main
from app.pipeline import OcrLine


@pytest.fixture
async def client():
    transport = ASGITransport(app=ocr_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_ocr_rejects_non_image(client):
    r = await client.post(
        "/ocr", files={"image": ("note.txt", b"hello", "text/plain")}
    )
    assert r.status_code == 400
    assert "not an image" in r.json()["detail"]


async def test_ocr_rejects_empty_file(client):
    r = await client.post("/ocr", files={"image": ("c.jpg", b"", "image/jpeg")})
    assert r.status_code == 400
    assert "empty" in r.json()["detail"]


async def test_ocr_success(client, monkeypatch):
    def fake_run_ocr(image_bytes):
        return [
            OcrLine("山田太郎", 0.95, [[0, 0], [100, 0], [100, 30], [0, 30]], 30),
            OcrLine("株式会社テスト", 0.9, [[0, 40], [100, 40], [100, 60], [0, 60]], 20),
            OcrLine("taro@example.com", 0.88, [[0, 70], [100, 70], [100, 85], [0, 85]], 15),
        ]

    monkeypatch.setattr(ocr_main, "run_ocr", fake_run_ocr)

    r = await client.post("/ocr", files={"image": ("c.jpg", IMAGE_BYTES, "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    assert body["fields"]["person_name"] == "山田太郎"
    assert body["fields"]["company"] == "株式会社テスト"
    assert body["fields"]["email"] == "taro@example.com"
    assert "山田太郎" in body["raw_text"]
    assert len(body["lines"]) == 3


async def test_ocr_handles_run_ocr_failure(client, monkeypatch):
    def boom(image_bytes):
        raise RuntimeError("paddle exploded")

    monkeypatch.setattr(ocr_main, "run_ocr", boom)
    r = await client.post("/ocr", files={"image": ("c.jpg", IMAGE_BYTES, "image/jpeg")})
    assert r.status_code == 500
    assert "ocr failed" in r.json()["detail"]


async def test_ocr_rejects_large_upload(client):
    r = await client.post("/ocr", files={"image": ("c.jpg", b"x" * (15 * 1024 * 1024 + 1), "image/jpeg")})
    assert r.status_code == 413


async def test_ocr_rejects_large_dimensions(client, monkeypatch):
    monkeypatch.setattr("app.images.MAX_IMAGE_PIXELS", 100)
    r = await client.post("/ocr", files={"image": ("c.jpg", IMAGE_BYTES, "image/jpeg")})
    assert r.status_code == 413


async def test_health_remains_available_and_model_runs_serially(client, monkeypatch):
    import asyncio
    import threading
    started, release = threading.Event(), threading.Event()
    calls = []
    def infer(data):
        calls.append(data)
        started.set()
        assert release.wait(5)
        return []
    monkeypatch.setattr(ocr_main, "run_ocr", infer)
    first = asyncio.create_task(client.post("/ocr", files={"image": ("c.jpg", IMAGE_BYTES, "image/jpeg")}))
    second = None
    try:
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(.01)
        assert started.is_set()
        second = asyncio.create_task(client.post("/ocr", files={"image": ("c.jpg", IMAGE_BYTES, "image/jpeg")}))
        await asyncio.sleep(.05)
        assert len(calls) == 1
        assert (await asyncio.wait_for(client.get("/healthz"), timeout=.5)).status_code == 200
    finally:
        release.set()
        assert (await first).status_code == 200
        if second:
            assert (await second).status_code == 200
    assert len(calls) == 2
