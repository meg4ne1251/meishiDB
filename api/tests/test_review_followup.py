"""Regressions found during the follow-up security and correctness review."""

import pytest


async def test_invalid_unicode_returns_validation_error(make_user):
    client, _ = await make_user()
    response = await client.post("/api/cards", content='{"fields":{"company":"\\ud800"}}',
                                 headers={"Content-Type": "application/json"})
    assert response.status_code == 422


async def test_validation_errors_do_not_echo_passwords(client):
    response = await client.post("/api/auth/register", json={
        "email": "safe@example.com", "display_name": "Safe", "password": "secret",
    })
    assert response.status_code == 422
    assert '"input"' not in response.text
    assert "secret" not in response.text


async def test_user_search_treats_wildcards_as_literal_text(make_user):
    await make_user(display_name="Other person")
    client, _ = await make_user()
    response = await client.get("/api/users/search", params={"q": "%%"})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("target", ["card", "memo", "register", "tag", "search"])
async def test_nul_text_is_rejected_before_database(make_user, target):
    client, _ = await make_user()
    if target == "card":
        response = await client.post("/api/cards", json={"fields": {"company": "a\x00b"}})
    elif target == "memo":
        card = (await client.post("/api/cards", json={})).json()
        response = await client.post(f"/api/cards/{card['id']}/memos", json={"body": "a\x00b"})
    elif target == "register":
        response = await client.post("/api/auth/register", json={
            "email": "nul@example.com", "display_name": "a\x00b", "password": "password123",
        })
    elif target == "tag":
        response = await client.post("/api/tags", json={"name": "a\x00b"})
    else:
        response = await client.get("/api/cards", params={"q": "a\x00b"})
    assert response.status_code == 422
    assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.parametrize("fails", [False, True])
async def test_old_ocr_cannot_modify_replaced_front_image(make_user, monkeypatch, fails):
    client, _ = await make_user()
    card = (await client.post("/api/cards", json={"source": "upload"})).json()
    path = f"/api/cards/{card['id']}"
    monkeypatch.setattr("app.services.images.validate_image", lambda _: None)
    monkeypatch.setattr("app.services.storage.is_configured", lambda: True)
    monkeypatch.setattr("app.services.storage.upload_card_image",
                        lambda cid, side, content, ct: (f"{cid}/{content.decode()}.jpg", None))

    async def infer(content):
        if content == b"old":
            replaced = await client.post(f"{path}/image",
                files={"image": ("new.jpg", b"new", "image/jpeg")})
            assert replaced.status_code == 200
            if fails:
                raise RuntimeError("old inference failed")
            return {"fields": {"company": "Old company"}, "raw_text": "Old text"}
        return {"fields": {"person_name": "New name"}, "raw_text": "New text"}

    monkeypatch.setattr("app.services.ocr_client.call_ocr", infer)
    response = await client.post(f"{path}/image", files={"image": ("old.jpg", b"old", "image/jpeg")})
    assert response.status_code == 200
    current = (await client.get(path)).json()
    assert current["image_front_key"].endswith("/new.jpg")
    assert current["fields"]["person_name"] == "New name"
    assert current["fields"]["company"] is None
    assert current["fields"]["raw_ocr_text"] == "New text"
    assert current["status"] == "ocr_done"


async def test_failed_ocr_preserves_concurrent_confirmation(make_user, monkeypatch):
    client, _ = await make_user()
    card = (await client.post("/api/cards", json={"source": "upload"})).json()
    path = f"/api/cards/{card['id']}"
    monkeypatch.setattr("app.services.images.validate_image", lambda _: None)
    monkeypatch.setattr("app.services.storage.is_configured", lambda: True)
    monkeypatch.setattr("app.services.storage.upload_card_image", lambda *args: ("front.jpg", None))

    async def infer(_):
        assert (await client.patch(path, json={"status": "confirmed"})).status_code == 200
        raise RuntimeError("inference failed")

    monkeypatch.setattr("app.services.ocr_client.call_ocr", infer)
    response = await client.post(f"{path}/image", files={"image": ("card.jpg", b"x", "image/jpeg")})
    assert response.status_code == 200
    assert (await client.get(path)).json()["status"] == "confirmed"


def test_image_replacements_use_distinct_object_and_thumbnail_keys(monkeypatch):
    from app.services import storage

    objects = {}
    monkeypatch.setattr(storage, "_is_configured", lambda: True)
    monkeypatch.setattr(storage, "_make_thumbnail", lambda data: b"thumb-" + data)
    monkeypatch.setattr(storage, "_put", lambda bucket, key, data, ct: objects.update({key: data}))
    first, first_thumb = storage.upload_card_image("card", "front", b"first", "image/jpeg")
    second, second_thumb = storage.upload_card_image("card", "front", b"second", "image/jpeg")
    assert first != second
    assert first_thumb != second_thumb
    assert objects[first] == b"first"
    assert objects[second] == b"second"
    assert first_thumb == first.rsplit(".", 1)[0] + "_512.webp"
    assert second_thumb == second.rsplit(".", 1)[0] + "_512.webp"
