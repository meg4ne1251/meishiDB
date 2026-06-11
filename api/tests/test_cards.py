"""名刺の CRUD・一覧フィルタ・お気に入り・アクセス制御。

Meilisearch / MinIO / geocoder はいずれも未設定（既定）なので、検索は Postgres ILIKE、
画像・座標は触らない経路を通る。
"""

from sqlalchemy import select

from app.models.audit import AuditLog


async def _create_card(client, *, source="manual", fields=None, tag_ids=None):
    payload = {"source": source}
    if fields is not None:
        payload["fields"] = fields
    if tag_ids is not None:
        payload["tag_ids"] = tag_ids
    r = await client.post("/api/cards", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_manual_card_is_confirmed(make_user):
    c, _ = await make_user()
    card = await _create_card(
        c, source="manual", fields={"person_name": "山田太郎", "company": "テスト株式会社"}
    )
    assert card["status"] == "confirmed"
    assert card["source"] == "manual"
    assert card["fields"]["person_name"] == "山田太郎"
    assert card["fields"]["company"] == "テスト株式会社"
    assert card["is_favorite"] is False
    assert card["tags"] == []


async def test_create_non_manual_card_is_uploaded(make_user):
    c, _ = await make_user()
    card = await _create_card(c, source="upload")
    assert card["status"] == "uploaded"


async def test_create_card_with_tags(make_user):
    c, _ = await make_user()
    t1 = (await c.post("/api/tags", json={"name": "A"})).json()
    t2 = (await c.post("/api/tags", json={"name": "B"})).json()
    card = await _create_card(c, tag_ids=[t1["id"], t2["id"]])
    names = sorted(t["name"] for t in card["tags"])
    assert names == ["A", "B"]


async def test_create_card_with_foreign_tag_rejected(make_user):
    c1, _ = await make_user(email="own@example.com")
    c2, _ = await make_user(email="other@example.com")
    foreign = (await c2.post("/api/tags", json={"name": "theirs"})).json()
    r = await c1.post("/api/cards", json={"tag_ids": [foreign["id"]]})
    assert r.status_code == 400
    assert "do not belong" in r.json()["detail"]


async def test_create_card_records_audit(make_user, db):
    c, user = await make_user()
    await _create_card(c)
    actions = (
        await db.scalars(select(AuditLog.action).where(AuditLog.user_id == user["id"]))
    ).all()
    assert "card.create" in actions


async def test_list_owned_cards_and_total(make_user):
    c, _ = await make_user()
    for i in range(3):
        await _create_card(c, fields={"person_name": f"P{i}"})
    r = await c.get("/api/cards")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


async def test_list_pagination(make_user):
    c, _ = await make_user()
    for i in range(5):
        await _create_card(c, fields={"person_name": f"P{i}"})
    r = await c.get("/api/cards?limit=2&offset=0")
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2

    r2 = await c.get("/api/cards?limit=2&offset=4")
    assert len(r2.json()["items"]) == 1


async def test_list_only_returns_own_cards(make_user):
    c1, _ = await make_user(email="a@example.com")
    c2, _ = await make_user(email="b@example.com")
    await _create_card(c1, fields={"person_name": "mine"})
    r = await c2.get("/api/cards")
    assert r.json()["total"] == 0


async def test_list_search_ilike_fallback(make_user):
    c, _ = await make_user()
    await _create_card(c, fields={"person_name": "田中花子", "company": "ABC商事"})
    await _create_card(c, fields={"person_name": "佐藤次郎", "company": "XYZ"})

    r = await c.get("/api/cards", params={"q": "ABC"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["fields"]["company"] == "ABC商事"

    r2 = await c.get("/api/cards", params={"q": "花子"})
    assert r2.json()["total"] == 1

    r3 = await c.get("/api/cards", params={"q": "存在しない"})
    assert r3.json()["total"] == 0


async def test_list_favorite_filter(make_user):
    c, _ = await make_user()
    card = await _create_card(c, fields={"person_name": "fav"})
    await _create_card(c, fields={"person_name": "nofav"})
    await c.post(f"/api/cards/{card['id']}/favorite")

    r = await c.get("/api/cards", params={"favorite": "true"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == card["id"]
    assert body["items"][0]["is_favorite"] is True


async def test_list_tag_filter(make_user):
    c, _ = await make_user()
    tag = (await c.post("/api/tags", json={"name": "filter-me"})).json()
    tagged = await _create_card(c, tag_ids=[tag["id"]])
    await _create_card(c)
    r = await c.get("/api/cards", params={"tag_id": tag["id"]})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == tagged["id"]


async def test_get_card_records_view_audit(make_user, db):
    c, user = await make_user()
    card = await _create_card(c)
    r = await c.get(f"/api/cards/{card['id']}")
    assert r.status_code == 200
    actions = (
        await db.scalars(select(AuditLog.action).where(AuditLog.user_id == user["id"]))
    ).all()
    assert "card.view" in actions


async def test_get_nonexistent_card_404(make_user):
    c, _ = await make_user()
    r = await c.get("/api/cards/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


async def test_get_other_users_card_is_404(make_user):
    c1, _ = await make_user(email="o@example.com")
    c2, _ = await make_user(email="x@example.com")
    card = await _create_card(c1)
    r = await c2.get(f"/api/cards/{card['id']}")
    assert r.status_code == 404


async def test_update_card_status(make_user):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.patch(f"/api/cards/{card['id']}", json={"status": "archived"})
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


async def test_update_card_invalid_status(make_user):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.patch(f"/api/cards/{card['id']}", json={"status": "bogus"})
    assert r.status_code == 400
    assert "invalid status" in r.json()["detail"]


async def test_update_card_fields(make_user):
    c, _ = await make_user()
    card = await _create_card(c, fields={"person_name": "old"})
    r = await c.patch(
        f"/api/cards/{card['id']}", json={"fields": {"person_name": "new", "title": "部長"}}
    )
    assert r.status_code == 200
    assert r.json()["fields"]["person_name"] == "new"
    assert r.json()["fields"]["title"] == "部長"


async def test_update_card_replaces_tags(make_user):
    c, _ = await make_user()
    t1 = (await c.post("/api/tags", json={"name": "T1"})).json()
    t2 = (await c.post("/api/tags", json={"name": "T2"})).json()
    card = await _create_card(c, tag_ids=[t1["id"]])
    r = await c.patch(f"/api/cards/{card['id']}", json={"tag_ids": [t2["id"]]})
    assert [t["name"] for t in r.json()["tags"]] == ["T2"]


async def test_delete_card_by_owner(make_user):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.delete(f"/api/cards/{card['id']}")
    assert r.status_code == 204
    assert (await c.get(f"/api/cards/{card['id']}")).status_code == 404


async def test_delete_card_by_non_owner_forbidden(make_user):
    c1, _ = await make_user(email="del-owner@example.com")
    c2, _ = await make_user(email="del-other@example.com")
    card = await _create_card(c1)
    r = await c2.delete(f"/api/cards/{card['id']}")
    assert r.status_code == 403


async def test_favorite_add_is_idempotent(make_user, db):
    from app.models.card import Favorite

    c, user = await make_user()
    card = await _create_card(c)
    assert (await c.post(f"/api/cards/{card['id']}/favorite")).status_code == 204
    assert (await c.post(f"/api/cards/{card['id']}/favorite")).status_code == 204

    favs = (
        await db.scalars(select(Favorite).where(Favorite.user_id == user["id"]))
    ).all()
    assert len(favs) == 1


async def test_remove_favorite(make_user):
    c, _ = await make_user()
    card = await _create_card(c)
    await c.post(f"/api/cards/{card['id']}/favorite")
    r = await c.delete(f"/api/cards/{card['id']}/favorite")
    assert r.status_code == 204
    body = (await c.get(f"/api/cards/{card['id']}")).json()
    assert body["is_favorite"] is False


async def test_remove_nonexistent_favorite_is_noop(make_user):
    c, _ = await make_user()
    card = await _create_card(c)
    r = await c.delete(f"/api/cards/{card['id']}/favorite")
    assert r.status_code == 204
