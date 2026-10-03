"""Regression coverage for the 2026-10-03 review."""

import asyncio
import csv
import io
import threading
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import BackgroundTasks, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.body_limit import BodyLimitMiddleware
from app.core.config import get_settings
from app.models.card import CardField
from app.routers import cards
from app.services import images, search_index


@pytest.mark.parametrize(
    "field", ["phone", "mobile", "address", "person_name_kana", "department", "title"]
)
async def test_list_and_export_search_same_fields(make_user, field):
    c, _ = await make_user()
    created = await c.post("/api/cards", json={"fields": {field: "review-unique"}})
    listing = await c.get("/api/cards", params={"q": "review-unique"})
    assert listing.json()["items"][0]["id"] == created.json()["id"]
    for format in ("csv", "vcard"):
        exported = await c.get("/api/export/cards", params={"q": "review-unique", "format": format})
        assert exported.status_code == 200


@pytest.mark.parametrize(
    "value", ["=1+1", "+1+1", "-1+1", "@SUM(A1:A2)", " \t=1", "\ttext", "\r=1", "\n=1", "＝1"]
)
async def test_csv_escapes_formula_cells(make_user, value):
    c, _ = await make_user()
    await c.post("/api/cards", json={"fields": {"person_name": value}})
    response = await c.get("/api/export/cards")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0]["person_name"] == "'" + value


async def test_invalid_source_returns_validation_error(make_user):
    c, _ = await make_user()
    r = await c.post("/api/cards", json={"source": "invalid-source"})
    assert r.status_code == 422


async def test_field_and_tag_edits_advance_updated_at(make_user):
    c, _ = await make_user()
    original = (await c.post("/api/cards", json={})).json()
    changed = (
        await c.patch(f"/api/cards/{original['id']}", json={"fields": {"person_name": "edited"}})
    ).json()
    assert changed["updated_at"] > original["updated_at"]
    tagged = (await c.patch(f"/api/cards/{original['id']}", json={"tag_ids": []})).json()
    assert tagged["updated_at"] > changed["updated_at"]


async def test_production_cookie_is_secure(make_user, monkeypatch):
    c, _ = await make_user(email="secure@example.com")
    monkeypatch.setattr(get_settings(), "app_env", "production")
    r = await c.post(
        "/api/auth/login", json={"email": "secure@example.com", "password": "password123"}
    )
    assert "Secure" in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"]


async def test_content_update_preserves_index_shares(monkeypatch):
    doc = {"id": "card", "shared_with": ["recipient"]}

    class Index:
        async def update_documents(self, documents):
            doc.update(documents[0])

        async def add_documents(self, documents):
            doc.clear()
            doc.update(documents[0])

    monkeypatch.setattr(search_index, "_is_configured", lambda: True)
    monkeypatch.setattr(search_index, "_index_ready", True)
    monkeypatch.setattr(
        search_index, "_get_async_client", lambda: SimpleNamespace(index=lambda _: Index())
    )
    await search_index.upsert_card(
        SimpleNamespace(id="card", owner_id="owner", status="confirmed"),
        SimpleNamespace(person_name="updated"),
    )
    assert doc["shared_with"] == ["recipient"]
    assert doc["person_name"] == "updated"


async def test_scanner_rejects_oversized_image_before_storage(client, make_user, monkeypatch):
    await make_user(email="scanner@example.com")
    monkeypatch.setattr(get_settings(), "scanner_owner_email", "scanner@example.com")
    monkeypatch.setattr(get_settings(), "scanner_api_token", "token")
    monkeypatch.setattr("app.services.storage.is_configured", lambda: True)
    r = await client.post(
        "/api/scanner/import",
        headers={"X-Scanner-Token": "token"},
        files={"image": ("c.jpg", b"x" * (images.MAX_IMAGE_BYTES + 1), "image/jpeg")},
    )
    assert r.status_code == 413


async def test_read_limit_stops_before_reading_whole_upload():
    class Upload:
        content_type = "image/jpeg"
        total = 0

        async def read(self, size):
            assert size > 0
            self.total += size
            return b"x" * size

    upload = Upload()
    with pytest.raises(Exception) as error:
        await images.read_image(upload, max_bytes=10)
    assert error.value.status_code == 413
    assert upload.total == 11


def test_image_dimension_limit(monkeypatch):
    data = io.BytesIO()
    Image.new("RGB", (30, 30)).save(data, format="PNG")
    monkeypatch.setattr(images, "MAX_IMAGE_PIXELS", 500)
    with pytest.raises(Exception) as error:
        images.validate_image(data.getvalue())
    assert error.value.status_code == 413


@pytest.mark.parametrize("chunked", [False, True])
async def test_body_limit_before_parsing(chunked):
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, max_bytes=10)

    @app.post("/")
    async def receive(request: Request):
        await request.body()
        return {"ok": True}

    async def chunks():
        yield b"123456"
        yield b"789012"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/", content=chunks() if chunked else b"123456789012")
    assert r.status_code == 413


async def test_ocr_address_schedules_geocoding(make_user, db):
    c, _ = await make_user()
    original = (await c.post("/api/cards", json={})).json()
    card, _ = await cards._ensure_access(
        db, UUID(original["id"]), SimpleNamespace(id=UUID(original["owner_id"]))
    )
    tasks = BackgroundTasks()
    await cards._apply_ocr_result(db, card, {"fields": {"address": "東京都"}}, tasks)
    assert len(tasks.tasks) == 1
    assert tasks.tasks[0].func is cards._geocode_card_in_background
    assert card.updated_at.isoformat() > original["updated_at"]


async def test_background_geocode_does_not_write_for_changed_address(make_user, monkeypatch):
    import app.core.db as dbmod

    c, _ = await make_user()
    original = (await c.post("/api/cards", json={"fields": {"address": "before"}})).json()
    cid = UUID(original["id"])
    monkeypatch.setattr(cards, "SessionLocal", dbmod.SessionLocal)
    monkeypatch.setattr("app.services.geocoder.is_configured", lambda: True)

    async def geocode(address):
        assert address == "before"
        async with dbmod.SessionLocal() as db:
            field = await db.get(CardField, cid)
            field.address = "after"
            await db.commit()
        return 35.0, 139.0

    monkeypatch.setattr("app.services.geocoder.geocode", geocode)
    await cards._geocode_card_in_background(cid)
    async with dbmod.SessionLocal() as db:
        field = await db.get(CardField, cid)
        assert field.address == "after"
        assert field.latitude is None


async def test_storage_delay_does_not_block_health(make_user, monkeypatch):
    c, _ = await make_user()
    original = (await c.post("/api/cards", json={})).json()
    monkeypatch.setattr("app.services.storage.is_configured", lambda: True)
    monkeypatch.setattr(images, "validate_image", lambda _: None)
    started, release = threading.Event(), threading.Event()

    def store(*args):
        started.set()
        assert release.wait(5)
        return "front.jpg", None

    monkeypatch.setattr("app.services.storage.upload_card_image", store)
    task = asyncio.create_task(
        c.post(
            f"/api/cards/{original['id']}/image",
            data={"run_ocr": "false"},
            files={"image": ("c.jpg", b"x", "image/jpeg")},
        )
    )
    try:
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        assert (await asyncio.wait_for(c.get("/healthz"), timeout=0.5)).status_code == 200
    finally:
        release.set()
        response = await task
    assert response.status_code == 200
