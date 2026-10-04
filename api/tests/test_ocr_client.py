"""OCR サービスへの薄いプロキシ ocr_client.call_ocr。"""

from app.core.config import get_settings
from app.services import ocr_client


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    last_url: str | None = None
    last_files: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, files=None):
        type(self).last_url = url
        type(self).last_files = files
        return _FakeResponse({"fields": {"person_name": "太郎"}, "raw_text": "太郎"})


async def test_call_ocr_posts_image_and_returns_json(monkeypatch):
    monkeypatch.setattr(get_settings(), "ocr_service_url", "http://ocr:8000")
    monkeypatch.setattr(ocr_client.httpx, "AsyncClient", _FakeAsyncClient)

    result = await ocr_client.call_ocr(b"imagebytes")
    assert result == {"fields": {"person_name": "太郎"}, "raw_text": "太郎"}
    # 末尾スラッシュを正規化して /ocr に投げる
    assert _FakeAsyncClient.last_url == "http://ocr:8000/ocr"
    assert "image" in _FakeAsyncClient.last_files


async def test_call_ocr_strips_trailing_slash(monkeypatch):
    monkeypatch.setattr(get_settings(), "ocr_service_url", "http://ocr:8000/")
    monkeypatch.setattr(ocr_client.httpx, "AsyncClient", _FakeAsyncClient)
    await ocr_client.call_ocr(b"x")
    assert _FakeAsyncClient.last_url == "http://ocr:8000/ocr"


async def test_invalid_ocr_does_not_expose_contact_data(monkeypatch):
    import pytest

    async def infer(_):
        return {"fields": {"company": "PRIVATE-CONTACT\x00"}}

    monkeypatch.setattr(ocr_client, "call_ocr", infer)
    with pytest.raises(ValueError, match="^invalid OCR response$"):
        await ocr_client.call_ocr_limited(b"image")
