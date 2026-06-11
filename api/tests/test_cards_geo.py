"""地図用 /cards/geo エンドポイント。座標を持つ名刺だけを返す。"""

from sqlalchemy import select

from app.models.card import Card, CardField


async def _create_card(client, **fields):
    r = await client.post("/api/cards", json={"source": "manual", "fields": fields})
    assert r.status_code == 201, r.text
    return r.json()


async def _set_coords(db, card_id, lat, lng):
    field = await db.scalar(select(CardField).where(CardField.card_id == card_id))
    field.latitude = lat
    field.longitude = lng
    await db.commit()


async def test_geo_returns_only_cards_with_coords(make_user, db):
    c, _ = await make_user()
    with_coords = await _create_card(c, person_name="座標あり", address="東京都港区")
    await _create_card(c, person_name="座標なし")
    await _set_coords(db, with_coords["id"], 35.66, 139.75)

    r = await c.get("/api/cards/geo")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == with_coords["id"]
    assert items[0]["latitude"] == 35.66
    assert items[0]["longitude"] == 139.75
    assert items[0]["person_name"] == "座標あり"


async def test_geo_scope_owned_excludes_others(make_user, db):
    c1, _ = await make_user(email="g1@example.com")
    c2, _ = await make_user(email="g2@example.com")
    card = await _create_card(c1, person_name="他人の")
    await _set_coords(db, card["id"], 35.0, 139.0)

    r = await c2.get("/api/cards/geo", params={"scope": "owned"})
    assert r.json()["items"] == []


async def test_geo_shared_scope(make_user, db):
    owner_c, _ = await make_user(email="go@example.com")
    target_c, _ = await make_user(email="gt@example.com")
    card = await _create_card(owner_c, person_name="共有座標", address="大阪")
    await _set_coords(db, card["id"], 34.69, 135.50)
    await owner_c.post(
        f"/api/cards/{card['id']}/shares", json={"user_email": "gt@example.com"}
    )

    shared = (await target_c.get("/api/cards/geo", params={"scope": "shared"})).json()
    assert len(shared["items"]) == 1
    assert shared["items"][0]["shared"] is True

    allc = (await target_c.get("/api/cards/geo", params={"scope": "all"})).json()
    assert len(allc["items"]) == 1


async def test_geo_requires_auth(client):
    r = await client.get("/api/cards/geo")
    assert r.status_code == 401
