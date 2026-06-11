"""スキャナ取り込みエンドポイント /scanner/import（X-Scanner-Token 認証）。"""

import pytest

from app.core.config import get_settings

OWNER_EMAIL = "scanner-owner@example.com"
TOKEN = "secret-scanner-token"


@pytest.fixture
def scanner_config(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "scanner_api_token", TOKEN)
    monkeypatch.setattr(s, "scanner_owner_email", OWNER_EMAIL)


@pytest.fixture
def storage_stub(monkeypatch):
    def upload(card_id, side, content, content_type):
        return f"{card_id}/{side}.jpg", f"{card_id}/{side}_512.webp"

    monkeypatch.setattr("app.services.storage.is_configured", lambda: True)
    monkeypatch.setattr("app.services.storage.upload_card_image", upload)


@pytest.fixture
def ocr_stub(monkeypatch):
    async def fake(content):
        return {
            "fields": {"person_name": "名刺太郎"},
            "confidence": {},
            "raw_text": "名刺太郎",
        }

    monkeypatch.setattr("app.services.ocr_client.call_ocr", fake)


async def test_scanner_not_configured(client):
    r = await client.post(
        "/api/scanner/import", files={"image": ("c.jpg", b"x", "image/jpeg")}
    )
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]


async def test_scanner_invalid_token(client, scanner_config, storage_stub):
    r = await client.post(
        "/api/scanner/import",
        files={"image": ("c.jpg", b"x", "image/jpeg")},
        headers={"X-Scanner-Token": "wrong"},
    )
    assert r.status_code == 401
    assert "invalid scanner token" in r.json()["detail"]


async def test_scanner_storage_not_configured(client, scanner_config):
    r = await client.post(
        "/api/scanner/import",
        files={"image": ("c.jpg", b"x", "image/jpeg")},
        headers={"X-Scanner-Token": TOKEN},
    )
    assert r.status_code == 503
    assert "storage" in r.json()["detail"]


async def test_scanner_unsupported_type(client, scanner_config, storage_stub):
    r = await client.post(
        "/api/scanner/import",
        files={"image": ("c.gif", b"x", "image/gif")},
        headers={"X-Scanner-Token": TOKEN},
    )
    assert r.status_code == 400


async def test_scanner_owner_not_found(client, scanner_config, storage_stub):
    # OWNER_EMAIL のユーザーがまだ居ない
    r = await client.post(
        "/api/scanner/import",
        files={"image": ("c.jpg", b"x", "image/jpeg")},
        headers={"X-Scanner-Token": TOKEN},
    )
    assert r.status_code == 500
    assert "owner" in r.json()["detail"]


async def test_scanner_success(client, make_user, scanner_config, storage_stub, ocr_stub):
    # 取り込み先オーナーを登録
    await make_user(email=OWNER_EMAIL)
    r = await client.post(
        "/api/scanner/import",
        files={"image": ("c.jpg", b"imagedata", "image/jpeg")},
        headers={"X-Scanner-Token": TOKEN},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "scanner"
    assert body["status"] == "ocr_done"
    assert body["fields"]["person_name"] == "名刺太郎"
    assert body["image_front_key"].endswith("/front.jpg")


async def test_scanner_ocr_failure_sets_uploaded(
    client, make_user, scanner_config, storage_stub, monkeypatch
):
    await make_user(email=OWNER_EMAIL)

    async def boom(content):
        raise RuntimeError("ocr down")

    monkeypatch.setattr("app.services.ocr_client.call_ocr", boom)
    r = await client.post(
        "/api/scanner/import",
        files={"image": ("c.jpg", b"imagedata", "image/jpeg")},
        headers={"X-Scanner-Token": TOKEN},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "uploaded"
