"""名刺メモの永続化・共有権限・監査ログを実 PostgreSQL で検証。"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.card import CardMemo


async def make_card(client):
    response = await client.post("/api/cards", json={"source": "manual"})
    assert response.status_code == 201
    return response.json()["id"]


async def make_memo(client, card_id, body="展示会で名刺交換\n資料を送る"):
    response = await client.post(f"/api/cards/{card_id}/memos", json={"body": body})
    assert response.status_code == 201
    return response.json()


async def share(owner, card_id, email, permission="edit"):
    response = await owner.post(
        f"/api/cards/{card_id}/shares",
        json={"user_email": email, "permission": permission},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_memo_crud_and_audit(make_user, db):
    client, user = await make_user(display_name="山田")
    card_id = await make_card(client)
    base = f"/api/cards/{card_id}/memos"
    assert (await client.get(base)).json() == {"items": [], "can_create": True}
    memo = await make_memo(client, card_id, "  展示会で名刺交換\n資料を送る  ")
    assert memo["body"] == "展示会で名刺交換\n資料を送る"
    assert memo["author_id"] == user["id"]
    assert memo["author_name"] == "山田"
    assert memo["created_at"]
    assert memo["can_edit"] and memo["can_delete"]
    later = await make_memo(client, card_id, "次回は来週")
    items = (await client.get(base)).json()["items"]
    assert [item["id"] for item in items] == [later["id"], memo["id"]]
    response = await client.patch(f"{base}/{memo['id']}", json={"body": "  送付済み  "})
    assert response.status_code == 200
    assert response.json()["body"] == "送付済み"
    assert response.json()["created_at"] == memo["created_at"]
    assert (await client.delete(f"{base}/{memo['id']}")).status_code == 204
    assert [item["id"] for item in (await client.get(base)).json()["items"]] == [later["id"]]
    logs = list(
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.target_id == card_id, AuditLog.action.like("card.memo_%"))
            .order_by(AuditLog.id)
        )
    )
    assert [log.action for log in logs] == [
        "card.memo_create",
        "card.memo_create",
        "card.memo_update",
        "card.memo_delete",
    ]
    assert all(str(log.user_id) == user["id"] for log in logs)
    assert all(log.audit_metadata == {"memo_id": memo["id"]} for log in (logs[0], *logs[2:]))


@pytest.mark.parametrize("body", ["", "   \n\t", "あ" * 5001, None, 123])
async def test_invalid_memo_body_rejected_for_create_and_update(make_user, body):
    client, _ = await make_user()
    card_id = await make_card(client)
    memo = await make_memo(client, card_id)
    base = f"/api/cards/{card_id}/memos"
    assert (await client.post(base, json={"body": body})).status_code == 422
    assert (await client.patch(f"{base}/{memo['id']}", json={"body": body})).status_code == 422
    assert (await client.get(base)).json()["items"][0]["body"] == memo["body"]


async def test_memo_body_at_limit(make_user):
    client, _ = await make_user()
    card_id = await make_card(client)
    memo = await make_memo(client, card_id, "あ" * 5000)
    assert len(memo["body"]) == 5000


async def assert_no_access(client, card_id, memo_id, status):
    base = f"/api/cards/{card_id}/memos"
    assert (await client.get(base)).status_code == status
    assert (await client.post(base, json={"body": "不正追加"})).status_code == status
    assert (
        await client.patch(f"{base}/{memo_id}", json={"body": "不正編集"})
    ).status_code == status
    assert (await client.delete(f"{base}/{memo_id}")).status_code == status


async def test_anonymous_and_unshared_users_cannot_access(make_user, client):
    owner, _ = await make_user()
    stranger, _ = await make_user()
    card_id = await make_card(owner)
    memo = await make_memo(owner, card_id)
    await assert_no_access(client, card_id, memo["id"], 401)
    await assert_no_access(stranger, card_id, memo["id"], 404)
    await assert_no_access(owner, uuid4(), memo["id"], 404)


async def test_view_share_reads_but_cannot_write(make_user):
    owner, _ = await make_user()
    viewer, user = await make_user()
    card_id = await make_card(owner)
    memo = await make_memo(owner, card_id)
    await share(owner, card_id, user["email"], "view")
    base = f"/api/cards/{card_id}/memos"
    result = (await viewer.get(base)).json()
    assert not result["can_create"]
    assert result["items"][0]["body"] == memo["body"]
    assert not result["items"][0]["can_edit"]
    assert not result["items"][0]["can_delete"]
    assert (await viewer.post(base, json={"body": "追加"})).status_code == 403
    assert (await viewer.patch(f"{base}/{memo['id']}", json={"body": "編集"})).status_code == 403
    assert (await viewer.delete(f"{base}/{memo['id']}")).status_code == 403


async def test_editor_manages_own_memos_and_owner_manages_all(make_user):
    owner, _ = await make_user()
    editor, user = await make_user()
    other, other_user = await make_user()
    card_id = await make_card(owner)
    owner_memo = await make_memo(owner, card_id)
    await share(owner, card_id, user["email"])
    await share(owner, card_id, other_user["email"])
    base = f"/api/cards/{card_id}/memos"
    own_memo = await make_memo(editor, card_id)
    other_memo = await make_memo(other, card_id)
    result = (await editor.get(base)).json()
    assert result["can_create"]
    assert {item["id"]: item["can_edit"] for item in result["items"]} == {
        owner_memo["id"]: False,
        own_memo["id"]: True,
        other_memo["id"]: False,
    }
    for memo in (owner_memo, other_memo):
        assert (
            await editor.patch(f"{base}/{memo['id']}", json={"body": "編集"})
        ).status_code == 403
        assert (await editor.delete(f"{base}/{memo['id']}")).status_code == 403
    assert (
        await editor.patch(f"{base}/{own_memo['id']}", json={"body": "自分の編集"})
    ).status_code == 200
    response = await owner.patch(f"{base}/{own_memo['id']}", json={"body": "所有者の編集"})
    assert response.status_code == 200
    assert response.json()["author_id"] == user["id"]
    assert all(item["can_delete"] for item in (await owner.get(base)).json()["items"])
    assert (await editor.delete(f"{base}/{own_memo['id']}")).status_code == 204
    assert (await owner.delete(f"{base}/{other_memo['id']}")).status_code == 204


async def test_downgrade_and_revocation_remove_author_write_access(make_user):
    owner, _ = await make_user()
    editor, user = await make_user()
    card_id = await make_card(owner)
    await share(owner, card_id, user["email"])
    memo = await make_memo(editor, card_id)
    share_id = await share(owner, card_id, user["email"], "view")
    base = f"/api/cards/{card_id}/memos"
    result = (await editor.get(base)).json()
    assert not result["can_create"] and not result["items"][0]["can_edit"]
    assert (await editor.patch(f"{base}/{memo['id']}", json={"body": "編集"})).status_code == 403
    assert (await editor.delete(f"{base}/{memo['id']}")).status_code == 403
    assert (await owner.delete(f"/api/cards/{card_id}/shares/{share_id}")).status_code == 204
    await assert_no_access(editor, card_id, memo["id"], 404)


async def test_memo_id_must_belong_to_card_and_delete_cascades(make_user, db):
    client, _ = await make_user()
    card_id = await make_card(client)
    other_card_id = await make_card(client)
    memo = await make_memo(client, card_id)
    assert (await client.get(f"/api/cards/{other_card_id}/memos")).json()["items"] == []
    for card, memo_id in [(other_card_id, memo["id"]), (card_id, str(uuid4()))]:
        path = f"/api/cards/{card}/memos/{memo_id}"
        assert (await client.patch(path, json={"body": "編集"})).status_code == 404
        assert (await client.delete(path)).status_code == 404
    assert (await client.delete(f"/api/cards/{card_id}")).status_code == 204
    assert await db.scalar(select(CardMemo).where(CardMemo.card_id == card_id)) is None
