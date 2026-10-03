"""共有（card_shares）と共有相手のアクセス権。"""

from sqlalchemy import select

from app.models.audit import AuditLog


async def _create_card(client, **fields):
    r = await client.post("/api/cards", json={"source": "manual", "fields": fields})
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_share_and_list(make_user):
    owner_c, _ = await make_user(email="owner@example.com")
    _, target = await make_user(email="target@example.com")
    card = await _create_card(owner_c, person_name="共有テスト")

    r = await owner_c.post(
        f"/api/cards/{card['id']}/shares",
        json={"user_email": "target@example.com", "permission": "view"},
    )
    assert r.status_code == 201
    share = r.json()
    assert share["shared_with"] == target["id"]
    assert share["permission"] == "view"

    listed = (await owner_c.get(f"/api/cards/{card['id']}/shares")).json()
    assert len(listed) == 1


async def test_shared_user_can_view_card(make_user):
    owner_c, _ = await make_user(email="ov@example.com")
    target_c, _ = await make_user(email="tv@example.com")
    card = await _create_card(owner_c, person_name="可視")
    await owner_c.post(
        f"/api/cards/{card['id']}/shares", json={"user_email": "tv@example.com"}
    )

    r = await target_c.get(f"/api/cards/{card['id']}")
    assert r.status_code == 200
    assert r.json()["shared"] is True

    # scope=shared 一覧に出る
    lst = (await target_c.get("/api/cards", params={"scope": "shared"})).json()
    assert lst["total"] == 1
    # scope=owned には出ない
    owned = (await target_c.get("/api/cards", params={"scope": "owned"})).json()
    assert owned["total"] == 0
    # scope=all には出る
    allc = (await target_c.get("/api/cards", params={"scope": "all"})).json()
    assert allc["total"] == 1


async def test_duplicate_share_updates_permission(make_user):
    owner_c, _ = await make_user(email="od@example.com")
    await make_user(email="td@example.com")
    card = await _create_card(owner_c)

    r1 = await owner_c.post(
        f"/api/cards/{card['id']}/shares",
        json={"user_email": "td@example.com", "permission": "view"},
    )
    r2 = await owner_c.post(
        f"/api/cards/{card['id']}/shares",
        json={"user_email": "td@example.com", "permission": "edit"},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    # 重複でなく更新（1 件のまま、permission は edit）
    listed = (await owner_c.get(f"/api/cards/{card['id']}/shares")).json()
    assert len(listed) == 1
    assert listed[0]["permission"] == "edit"


async def test_cannot_share_with_self(make_user):
    owner_c, _ = await make_user(email="self@example.com")
    card = await _create_card(owner_c)
    r = await owner_c.post(
        f"/api/cards/{card['id']}/shares", json={"user_email": "self@example.com"}
    )
    assert r.status_code == 400
    assert "yourself" in r.json()["detail"]


async def test_share_with_unknown_user_404(make_user):
    owner_c, _ = await make_user(email="ou@example.com")
    card = await _create_card(owner_c)
    r = await owner_c.post(
        f"/api/cards/{card['id']}/shares", json={"user_email": "ghost@example.com"}
    )
    assert r.status_code == 404
    assert "user not found" in r.json()["detail"]


async def test_non_owner_cannot_share(make_user):
    owner_c, _ = await make_user(email="real-owner@example.com")
    other_c, _ = await make_user(email="intruder@example.com")
    card = await _create_card(owner_c)
    r = await other_c.post(
        f"/api/cards/{card['id']}/shares", json={"user_email": "intruder@example.com"}
    )
    assert r.status_code == 404


async def test_invalid_permission_rejected(make_user):
    owner_c, _ = await make_user(email="perm@example.com")
    await make_user(email="permtarget@example.com")
    card = await _create_card(owner_c)
    r = await owner_c.post(
        f"/api/cards/{card['id']}/shares",
        json={"user_email": "permtarget@example.com", "permission": "admin"},
    )
    assert r.status_code == 422


async def test_view_share_is_read_only(make_user):
    owner_c, _ = await make_user(email="ro-owner@example.com")
    target_c, _ = await make_user(email="ro-target@example.com")
    card = await _create_card(owner_c, person_name="ro")
    await owner_c.post(
        f"/api/cards/{card['id']}/shares",
        json={"user_email": "ro-target@example.com", "permission": "view"},
    )
    r = await target_c.patch(
        f"/api/cards/{card['id']}", json={"fields": {"person_name": "hacked"}}
    )
    assert r.status_code == 403
    assert "read-only" in r.json()["detail"]


async def test_edit_share_allows_field_update_but_not_tags(make_user):
    owner_c, _ = await make_user(email="ed-owner@example.com")
    target_c, _ = await make_user(email="ed-target@example.com")
    card = await _create_card(owner_c, person_name="before")
    await owner_c.post(
        f"/api/cards/{card['id']}/shares",
        json={"user_email": "ed-target@example.com", "permission": "edit"},
    )

    # フィールド更新は OK
    r = await target_c.patch(
        f"/api/cards/{card['id']}", json={"fields": {"person_name": "after"}}
    )
    assert r.status_code == 200
    assert r.json()["fields"]["person_name"] == "after"

    # タグ操作はオーナー専権 → 403
    tag = (await target_c.post("/api/tags", json={"name": "mine"})).json()
    r2 = await target_c.patch(f"/api/cards/{card['id']}", json={"tag_ids": [tag["id"]]})
    assert r2.status_code == 403
    assert "managed by the owner" in r2.json()["detail"]


async def test_shared_user_cannot_delete_card(make_user):
    owner_c, _ = await make_user(email="sd-owner@example.com")
    target_c, _ = await make_user(email="sd-target@example.com")
    card = await _create_card(owner_c)
    await owner_c.post(
        f"/api/cards/{card['id']}/shares",
        json={"user_email": "sd-target@example.com", "permission": "edit"},
    )
    r = await target_c.delete(f"/api/cards/{card['id']}")
    assert r.status_code == 403


async def test_delete_share_revokes_access(make_user):
    owner_c, _ = await make_user(email="rev-owner@example.com")
    target_c, _ = await make_user(email="rev-target@example.com")
    card = await _create_card(owner_c)
    share = (
        await owner_c.post(
            f"/api/cards/{card['id']}/shares",
            json={"user_email": "rev-target@example.com"},
        )
    ).json()

    # 取り消し前は閲覧可
    assert (await target_c.get(f"/api/cards/{card['id']}")).status_code == 200

    r = await owner_c.delete(f"/api/cards/{card['id']}/shares/{share['id']}")
    assert r.status_code == 204

    # 取り消し後は 404
    assert (await target_c.get(f"/api/cards/{card['id']}")).status_code == 404


async def test_delete_share_records_audit(make_user, db):
    owner_c, owner = await make_user(email="audit-owner@example.com")
    _, target = await make_user(email="audit-target@example.com")
    card = await _create_card(owner_c)
    share = (
        await owner_c.post(
            f"/api/cards/{card['id']}/shares",
            json={"user_email": "audit-target@example.com", "permission": "edit"},
        )
    ).json()

    r = await owner_c.delete(f"/api/cards/{card['id']}/shares/{share['id']}")
    assert r.status_code == 204

    row = await db.scalar(
        select(AuditLog).where(
            AuditLog.user_id == owner["id"], AuditLog.action == "card.share_revoke"
        )
    )
    assert row is not None
    assert row.target_id == card["id"]
    assert row.audit_metadata["shared_with"] == target["id"]
    assert row.audit_metadata["permission"] == "edit"


async def test_delete_share_wrong_card_404(make_user):
    owner_c, _ = await make_user(email="wc-owner@example.com")
    await make_user(email="wc-target@example.com")
    card1 = await _create_card(owner_c)
    card2 = await _create_card(owner_c)
    share = (
        await owner_c.post(
            f"/api/cards/{card1['id']}/shares",
            json={"user_email": "wc-target@example.com"},
        )
    ).json()
    # 別カードの URL で消そうとすると 404
    r = await owner_c.delete(f"/api/cards/{card2['id']}/shares/{share['id']}")
    assert r.status_code == 404


async def test_non_owner_cannot_revoke_share(make_user):
    owner_c, _ = await make_user(email="nr-owner@example.com")
    target_c, _ = await make_user(email="nr-target@example.com")
    card = await _create_card(owner_c)
    share = (
        await owner_c.post(
            f"/api/cards/{card['id']}/shares",
            json={"user_email": "nr-target@example.com", "permission": "edit"},
        )
    ).json()
    r = await target_c.delete(f"/api/cards/{card['id']}/shares/{share['id']}")
    assert r.status_code == 403
