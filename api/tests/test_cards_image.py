"""画像アップロード・取得・OCR 再実行。

MinIO / OCR サービスは monkeypatch でスタブ化し、ルーターの分岐だけを検証する。
"""

import pytest

from app.routers import cards as cards_router


async def _create_card(client, **fields):
    r = await client.post("/api/cards", json={"source": "upload", "fields": fields})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def storage_stub(monkeypatch):
    monkeypatch.setattr("app.services.images.validate_image", lambda content: None)
    """MinIO を「設定済み」に見せて、保存・取得をメモリ上で完結させる。"""
    store: dict[str, bytes] = {}

    def upload(card_id, side, content, content_type):
        key = f"{card_id}/{side}.jpg"
        store[key] = content
        return key, f"{card_id}/{side}_512.webp"

    def get_image(key, *, thumb=False):
        if key not in store:
            raise FileNotFoundError(key)
        return store[key], "image/jpeg"

    monkeypatch.setattr("app.services.storage.is_configured", lambda: True)
    monkeypatch.setattr("app.services.storage.upload_card_image", upload)
    monkeypatch.setattr("app.services.storage.get_card_image", get_image)
    monkeypatch.setattr("app.services.storage.delete_card_images", lambda card_id: None)
    return store


@pytest.fixture
def ocr_stub(monkeypatch):
    async def fake_call_ocr(content):
        return {
            "fields": {"person_name": "OCR太郎", "company": "OCR社"},
            "confidence": {"person_name": 0.91},
            "raw_text": "OCR太郎\nOCR社",
        }

    monkeypatch.setattr("app.services.ocr_client.call_ocr", fake_call_ocr)


async def test_upload_requires_storage_configured(make_user):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"x", "image/jpeg")},
        data={"side": "front"},
    )
    assert r.status_code == 503


async def test_upload_unsupported_type(make_user, storage_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.gif", b"x", "image/gif")},
        data={"side": "front"},
    )
    assert r.status_code == 400
    assert "unsupported" in r.json()["detail"]


async def test_upload_empty_image(make_user, storage_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"", "image/jpeg")},
        data={"side": "front"},
    )
    assert r.status_code == 400
    assert "empty" in r.json()["detail"]


async def test_upload_too_large(make_user, storage_stub, monkeypatch):
    monkeypatch.setattr(cards_router, "MAX_IMAGE_BYTES", 10)
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"01234567890123456789", "image/jpeg")},
        data={"side": "front"},
    )
    assert r.status_code == 413


async def test_upload_front_runs_ocr(make_user, storage_stub, ocr_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"imagedata", "image/jpeg")},
        data={"side": "front", "run_ocr": "true"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["image_front_key"] == f"{card['id']}/front.jpg"
    assert body["status"] == "ocr_done"
    assert body["fields"]["person_name"] == "OCR太郎"
    assert body["fields"]["raw_ocr_text"].startswith("OCR太郎")


async def test_ocr_does_not_overwrite_existing_fields(make_user, storage_stub, ocr_stub):
    c, _ = await make_user()
    card = await _create_card(c, person_name="既存の名前")
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"imagedata", "image/jpeg")},
        data={"side": "front", "run_ocr": "true"},
    )
    # 既存の person_name は OCR で上書きされない。空だった company は埋まる。
    assert r.json()["fields"]["person_name"] == "既存の名前"
    assert r.json()["fields"]["company"] == "OCR社"


async def test_upload_front_without_ocr(make_user, storage_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"imagedata", "image/jpeg")},
        data={"side": "front", "run_ocr": "false"},
    )
    assert r.status_code == 200
    # run_ocr=false なので ocr_running/ocr_done に遷移しない
    assert r.json()["status"] == "uploaded"


async def test_upload_back_does_not_run_ocr(make_user, storage_stub, ocr_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("back.jpg", b"imagedata", "image/jpeg")},
        data={"side": "back"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["image_back_key"] == f"{card['id']}/back.jpg"
    # back は OCR しないので fields は空のまま
    assert body["fields"]["person_name"] is None


async def test_ocr_failure_resets_status(make_user, storage_stub, monkeypatch):
    async def boom(content):
        raise RuntimeError("ocr down")

    monkeypatch.setattr("app.services.ocr_client.call_ocr", boom)
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"imagedata", "image/jpeg")},
        data={"side": "front", "run_ocr": "true"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "uploaded"


async def test_shared_user_cannot_upload(make_user, storage_stub):
    owner_c, _ = await make_user(email="iu-owner@example.com")
    target_c, _ = await make_user(email="iu-target@example.com")
    card = await _create_card(owner_c)
    await owner_c.post(
        f"/api/cards/{card['id']}/shares",
        json={"user_email": "iu-target@example.com", "permission": "edit"},
    )
    r = await target_c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"x", "image/jpeg")},
        data={"side": "front"},
    )
    assert r.status_code == 403


async def test_get_image(make_user, storage_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"thebytes", "image/jpeg")},
        data={"side": "front", "run_ocr": "false"},
    )
    r = await c.get(f"/api/cards/{card['id']}/image", params={"side": "front"})
    assert r.status_code == 200
    assert r.content == b"thebytes"
    assert r.headers["content-type"].startswith("image/jpeg")


async def test_get_image_404_when_no_key(make_user, storage_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.get(f"/api/cards/{card['id']}/image", params={"side": "back"})
    assert r.status_code == 404


async def test_rerun_ocr_requires_front_image(make_user, storage_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.post(f"/api/cards/{card['id']}/ocr")
    assert r.status_code == 400
    assert "no front image" in r.json()["detail"]


async def test_rerun_ocr_success(make_user, storage_stub, ocr_stub):
    c, _ = await make_user()
    card = await _create_card(c)
    await c.post(
        f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"imagedata", "image/jpeg")},
        data={"side": "front", "run_ocr": "false"},
    )
    r = await c.post(f"/api/cards/{card['id']}/ocr")
    assert r.status_code == 200
    assert r.json()["status"] == "ocr_done"
    assert r.json()["fields"]["person_name"] == "OCR太郎"
