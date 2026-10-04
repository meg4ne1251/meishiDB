"""Regression tests for the second security and correctness review."""

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.models.card import Card, CardField, CardShare, Favorite
from app.models.user import User
from app.routers import webauthn
from app.services import search_index


async def test_untrusted_origin_cannot_logout(make_user):
    client, _ = await make_user()
    response = await client.post("/api/auth/logout", headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_trusted_origin_can_write(make_user):
    client, _ = await make_user()
    response = await client.post("/api/cards", json={}, headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 201


@pytest.mark.parametrize("payload", [
    {"email": ["invalid"]},
    {"email": {"invalid": True}},
])
async def test_malformed_passkey_begin_is_validation_error(client, payload):
    response = await client.post("/api/webauthn/login/begin", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("credential", ["invalid", {"rawId": "a"}, {"rawId": [1]}])
async def test_malformed_passkey_finish_is_client_error(client, credential):
    begin = (await client.post("/api/webauthn/login/begin", json={})).json()
    response = await client.post("/api/webauthn/login/finish", json={
        "challenge_id": begin["challenge_id"], "credential": credential,
    })
    assert response.status_code in {400, 422}


async def test_challenge_id_must_be_string(client):
    response = await client.post("/api/webauthn/login/finish", json={
        "challenge_id": ["invalid"], "credential": {"rawId": "YQ"},
    })
    assert response.status_code in {400, 422}


async def test_register_challenge_cannot_be_used_for_login(make_user, monkeypatch):
    client, _ = await make_user()
    begin = (await client.post("/api/webauthn/register/begin")).json()
    def verifier(**kwargs):
        pytest.fail("wrong-purpose challenge reached verifier")
    monkeypatch.setattr(webauthn, "verify_authentication_response", verifier)
    response = await client.post("/api/webauthn/login/finish", json={
        "challenge_id": begin["challenge_id"], "credential": {"rawId": "YQ"},
    })
    assert response.status_code == 400


async def test_concurrent_same_email_registration_is_client_error(client_factory, db):
    first, second = client_factory(), client_factory()
    payload = {"email": "race@example.com", "display_name": "Race", "password": "password123"}
    responses = await asyncio.gather(*(
        client.post("/api/auth/register", json=payload) for client in (first, second)
    ))
    assert sorted(response.status_code for response in responses) == [201, 400]
    assert len(list(await db.scalars(select(User)))) == 1


async def test_missing_original_after_thumbnail_failure_returns_404(make_user, monkeypatch):
    client, _ = await make_user()
    card = (await client.post("/api/cards", json={})).json()
    import app.core.db as dbmod
    async with dbmod.SessionLocal() as session:
        stored = await session.get(Card, UUID(card["id"]))
        stored.image_front_key = f"{card['id']}/front.jpg"
        await session.commit()

    def missing(*args, **kwargs):
        raise FileNotFoundError("internal-bucket-name")

    monkeypatch.setattr("app.services.storage.get_card_image", missing)
    response = await client.get(f"/api/cards/{card['id']}/image", params={"thumb": "true"})
    assert response.status_code == 404
    assert "internal-bucket-name" not in response.text


async def test_ocr_preserves_fields_edited_during_inference(make_user, monkeypatch):
    client, _ = await make_user()
    card = (await client.post("/api/cards", json={})).json()
    monkeypatch.setattr("app.services.images.validate_image", lambda _: None)
    monkeypatch.setattr("app.services.storage.is_configured", lambda: True)
    monkeypatch.setattr("app.services.storage.upload_card_image", lambda *args: ("front.jpg", None))

    async def infer(_):
        response = await client.patch(f"/api/cards/{card['id']}", json={
            "fields": {"person_name": "Manual edit"}, "status": "confirmed",
        })
        assert response.status_code == 200
        return {"fields": {"person_name": "OCR name", "company": "OCR company"}}

    monkeypatch.setattr("app.services.ocr_client.call_ocr", infer)
    response = await client.post(f"/api/cards/{card['id']}/image",
        files={"image": ("card.jpg", b"image", "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["fields"]["person_name"] == "Manual edit"
    assert response.json()["fields"]["company"] == "OCR company"
    assert response.json()["status"] == "confirmed"


async def test_tag_color_can_be_cleared(make_user):
    client, _ = await make_user()
    tag = (await client.post("/api/tags", json={"name": "Color", "color": "#ff0000"})).json()
    response = await client.patch(f"/api/tags/{tag['id']}", json={"color": None})
    assert response.status_code == 200
    assert response.json()["color"] is None


@pytest.mark.parametrize("newline", ["\r", "\r\n", "\n"])
async def test_vcard_newlines_cannot_inject_properties(make_user, newline):
    client, _ = await make_user()
    await client.post("/api/cards", json={"fields": {"company": f"Company{newline}EMAIL:evil@example.com"}})
    response = await client.get("/api/export/cards", params={"format": "vcard"})
    assert response.status_code == 200
    assert b"\rEMAIL:" not in response.content
    assert b"\nEMAIL:" not in response.content
    assert response.content.endswith(b"END:VCARD\r\n")


async def test_search_does_not_silently_truncate_at_200(make_user, db, monkeypatch):
    client, user = await make_user()
    identifiers = [uuid4() for _ in range(205)]
    for identifier in identifiers:
        db.add(Card(id=identifier, owner_id=UUID(user["id"])))
        db.add(CardField(card_id=identifier, company="Search company"))
    await db.commit()

    class Index:
        async def search(self, query, *, limit, offset=0, **kwargs):
            return SimpleNamespace(hits=[{"id": str(id)} for id in identifiers[offset:offset + limit]])

    monkeypatch.setattr(search_index, "_is_configured", lambda: True)
    monkeypatch.setattr(search_index, "_index_ready", True)
    monkeypatch.setattr(search_index, "_get_async_client", lambda: SimpleNamespace(index=lambda _: Index()))
    response = await client.get("/api/cards", params={"q": "Search", "offset": 200})
    assert response.json()["total"] == 205
    assert len(response.json()["items"]) == 5


async def test_concurrent_favorites_are_idempotent(make_user, db):
    client, _ = await make_user()
    card = (await client.post("/api/cards", json={})).json()
    responses = await asyncio.gather(*(client.post(f"/api/cards/{card['id']}/favorite") for _ in range(4)))
    assert all(response.status_code == 204 for response in responses)
    assert len(list(await db.scalars(select(Favorite)))) == 1


async def test_concurrent_shares_create_one_share(make_user, db):
    client, _ = await make_user()
    _, recipient = await make_user()
    card = (await client.post("/api/cards", json={})).json()
    responses = await asyncio.gather(*(client.post(f"/api/cards/{card['id']}/shares",
        json={"user_email": recipient["email"], "permission": "edit"}) for _ in range(4)))
    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert len(list(await db.scalars(select(CardShare)))) == 1


@pytest.mark.parametrize("permission, can_edit", [("view", False), ("edit", True)])
async def test_card_reports_edit_permission(make_user, permission, can_edit):
    owner, _ = await make_user()
    recipient, user = await make_user()
    card = (await owner.post("/api/cards", json={})).json()
    assert card["can_edit"] is True
    await owner.post(f"/api/cards/{card['id']}/shares", json={"user_email": user["email"], "permission": permission})
    assert (await recipient.get(f"/api/cards/{card['id']}")).json()["can_edit"] is can_edit
    assert (await recipient.get("/api/cards", params={"scope": "shared"})).json()["items"][0]["can_edit"] is can_edit


@pytest.mark.parametrize("headers", [
    {"Origin": "null"}, {"Origin": "http://localhost:3000.evil.example"},
    {"Referer": "http://evil.example/form"}, {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
async def test_browser_security_rejects_untrusted_writes(make_user, headers):
    client, _ = await make_user()
    assert (await client.post("/api/cards", json={}, headers=headers)).status_code == 403


async def test_private_json_is_not_cacheable(make_user):
    client, _ = await make_user()
    response = await client.get("/api/cards")
    assert response.headers["cache-control"] == "private, no-store"


async def test_auth_limits_and_window_reset(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.core import auth_limit

    now = 100.0
    monkeypatch.setattr(auth_limit, "monotonic", lambda: now)
    app = FastAPI()
    app.add_middleware(auth_limit.AuthRateLimitMiddleware, max_requests=2)

    @app.post("/api/auth/login")
    async def login():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/auth/login")).status_code == 200
        assert (await client.post("/api/auth/login")).status_code == 200
        blocked = await client.post("/api/auth/login", headers={"X-Forwarded-For": "203.0.113.2"})
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "60"
        now += 61
        assert (await client.post("/api/auth/login")).status_code == 200


async def test_passkey_challenges_are_bounded(client, monkeypatch):
    monkeypatch.setattr(webauthn, "_MAX_CHALLENGES", 1)
    assert (await client.post("/api/webauthn/login/begin", json={})).status_code == 200
    assert (await client.post("/api/webauthn/login/begin", json={})).status_code == 503
