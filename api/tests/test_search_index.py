"""Meilisearch 連携。未設定時は no-op、ドキュメント変換は純粋ロジック。"""

import uuid

from app.services import search_index


def test_is_configured_default_false():
    assert search_index._is_configured() is False


async def test_search_card_ids_none_when_not_configured():
    # 未設定なら Postgres ILIKE にフォールバックさせるため None を返す
    assert await search_index.search_card_ids(uuid.uuid4(), "query") is None


async def test_search_card_ids_none_for_blank_query():
    assert await search_index.search_card_ids(uuid.uuid4(), "   ") is None


async def test_upsert_and_delete_are_noop_when_not_configured():
    # 例外を投げないことだけ確認（設定が無ければ黙って何もしない）
    class _Card:
        id = uuid.uuid4()
        owner_id = uuid.uuid4()
        status = "confirmed"

    await search_index.upsert_card(_Card(), None)
    await search_index.update_shares(uuid.uuid4(), [uuid.uuid4()])
    await search_index.delete_card(uuid.uuid4())


def test_doc_for_card_with_fields():
    class _Card:
        id = uuid.uuid4()
        owner_id = uuid.uuid4()
        status = "confirmed"

    class _Fields:
        person_name = "山田"
        person_name_kana = "ヤマダ"
        company = "会社"
        department = "営業"
        title = "部長"
        email = "a@example.com"
        phone = "03-1111-2222"
        mobile = "090-0000-0000"
        address = "東京"
        raw_ocr_text = "raw"

    doc = search_index._doc_for_card(_Card(), _Fields())
    assert doc["id"] == str(_Card.id)
    assert doc["owner_id"] == str(_Card.owner_id)
    assert doc["shared_with"] == []
    assert doc["person_name"] == "山田"
    assert doc["company"] == "会社"
    assert doc["raw_ocr_text"] == "raw"


def test_doc_for_card_without_fields():
    class _Card:
        id = uuid.uuid4()
        owner_id = uuid.uuid4()
        status = "uploaded"

    doc = search_index._doc_for_card(_Card(), None)
    assert doc["person_name"] is None
    assert doc["company"] is None
    assert doc["shared_with"] == []
