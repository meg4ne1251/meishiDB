"""Meilisearch インデックス連携。

- index 名: `cards`
- ドキュメント ID: card.id (UUID 文字列)
- フィルタ可能属性: owner_id, shared_with (受け取った side でも検索できるよう配列)
- 検索可能属性: 各フィールド + raw_ocr_text

Meilisearch が未設定の場合、すべて no-op（`search_card_ids` は None を返し、ルーター側は Postgres ILIKE にフォールバック）。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.core.config import get_settings
from app.models.card import Card, CardField, CardShare
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_INDEX = "cards"
_client = None
_index_ready = False


def _is_configured() -> bool:
    return bool(get_settings().meilisearch_url)


def _get_async_client():
    """meilisearch-python-sdk の AsyncClient を返す。"""
    global _client
    if _client is not None:
        return _client
    if not _is_configured():
        return None
    from meilisearch_python_sdk import AsyncClient

    s = get_settings()
    _client = AsyncClient(s.meilisearch_url, api_key=s.meilisearch_key or None)
    return _client


async def _ensure_index_ready() -> None:
    """初回呼び出し時にインデックス＋設定を整える。"""
    global _index_ready
    if _index_ready or not _is_configured():
        return
    client = _get_async_client()
    if client is None:
        return
    index = client.index(_INDEX)
    try:
        await index.update_filterable_attributes(["owner_id", "shared_with"])
        await index.update_searchable_attributes(
            [
                "person_name",
                "person_name_kana",
                "company",
                "department",
                "title",
                "email",
                "phone",
                "mobile",
                "address",
                "raw_ocr_text",
            ]
        )
        _index_ready = True
    except Exception as e:
        logger.warning("meili index init failed: %s", e)


def _doc_for_card(card: Card, fields: CardField | None) -> dict[str, Any]:
    f = fields
    return {
        "id": str(card.id),
        "owner_id": str(card.owner_id),
        "shared_with": [],  # 共有更新時に shares 経由で再投入する
        "status": card.status,
        "person_name": getattr(f, "person_name", None) if f else None,
        "person_name_kana": getattr(f, "person_name_kana", None) if f else None,
        "company": getattr(f, "company", None) if f else None,
        "department": getattr(f, "department", None) if f else None,
        "title": getattr(f, "title", None) if f else None,
        "email": getattr(f, "email", None) if f else None,
        "phone": getattr(f, "phone", None) if f else None,
        "mobile": getattr(f, "mobile", None) if f else None,
        "address": getattr(f, "address", None) if f else None,
        "raw_ocr_text": getattr(f, "raw_ocr_text", None) if f else None,
    }


async def upsert_card(card: Card, fields: CardField | None) -> None:
    if not _is_configured():
        return
    try:
        await _ensure_index_ready()
        client = _get_async_client()
        if client is None:
            return
        await client.index(_INDEX).add_documents([_doc_for_card(card, fields)])
    except Exception as e:
        logger.warning("meili upsert failed (%s): %s", card.id, e)


async def update_shares(card_id: UUID, shared_with_ids: list[UUID]) -> None:
    if not _is_configured():
        return
    try:
        await _ensure_index_ready()
        client = _get_async_client()
        if client is None:
            return
        await client.index(_INDEX).update_documents(
            [
                {
                    "id": str(card_id),
                    "shared_with": [str(u) for u in shared_with_ids],
                }
            ]
        )
    except Exception as e:
        logger.warning("meili shares update failed (%s): %s", card_id, e)


async def delete_card(card_id: UUID) -> None:
    if not _is_configured():
        return
    try:
        client = _get_async_client()
        if client is None:
            return
        await client.index(_INDEX).delete_document(str(card_id))
    except Exception as e:
        logger.warning("meili delete failed (%s): %s", card_id, e)


async def search_card_ids(viewer_id: UUID, query: str) -> list[UUID] | None:
    """Meilisearch で検索し、可視 ID 一覧を返す。未設定なら None。"""
    if not _is_configured() or not query.strip():
        return None
    try:
        await _ensure_index_ready()
        client = _get_async_client()
        if client is None:
            return None
        result = await client.index(_INDEX).search(
            query,
            limit=200,
            filter=f'owner_id = "{viewer_id}" OR shared_with = "{viewer_id}"',
            attributes_to_retrieve=["id"],
        )
        hits = result.hits or []
        return [UUID(h["id"]) for h in hits]
    except Exception as e:
        logger.warning("meili search failed: %s", e)
        return None


async def reindex_all(db: AsyncSession) -> int:
    """全 card を Meili に再投入する（管理用）。"""
    if not _is_configured():
        return 0
    await _ensure_index_ready()
    client = _get_async_client()
    if client is None:
        return 0

    docs: list[dict[str, Any]] = []
    rows = await db.execute(select(Card, CardField).join(CardField, isouter=True))
    for card, fields in rows.all():
        docs.append(_doc_for_card(card, fields))

    # shared_with マッピングを別クエリで作る
    share_rows = await db.execute(select(CardShare.card_id, CardShare.shared_with))
    share_map: dict[str, list[str]] = {}
    for cid, uid in share_rows.all():
        share_map.setdefault(str(cid), []).append(str(uid))
    for d in docs:
        d["shared_with"] = share_map.get(d["id"], [])

    if docs:
        await client.index(_INDEX).add_documents(docs)
    return len(docs)
