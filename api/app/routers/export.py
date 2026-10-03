"""CSV / vCard エクスポート。

検索／タグ／お気に入りのフィルタは `/cards` と同じセマンティクスで揃える。
すべてのエクスポートは `audit_logs.action='card.export'` に必ず記録する。
"""

from __future__ import annotations

import csv
import io
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.deps import get_current_user
from app.models.card import Card, CardField, CardShare, CardTag, Favorite
from app.models.user import User
from app.services import audit
from app.services.card_query import apply_search

router = APIRouter(prefix="/export", tags=["export"])


CSV_COLUMNS = [
    "person_name",
    "person_name_kana",
    "company",
    "department",
    "title",
    "email",
    "phone",
    "mobile",
    "fax",
    "postal_code",
    "address",
    "website",
]


async def _resolve_cards(
    db: AsyncSession,
    user: User,
    *,
    scope: str,
    q: str | None,
    favorite: bool,
    tag_id: UUID | None,
    ids: list[UUID] | None,
) -> list[Card]:
    base = (
        select(Card)
        .options(selectinload(Card.fields))
        .order_by(Card.updated_at.desc())
    )

    if ids:
        # 明示 ID 指定が最優先。アクセス権チェックは下で行う
        base = base.where(Card.id.in_(ids))
    else:
        shared_card_ids = (
            select(CardShare.card_id).where(CardShare.shared_with == user.id).scalar_subquery()
        )
        if scope == "owned":
            base = base.where(Card.owner_id == user.id)
        elif scope == "shared":
            base = base.where(Card.id.in_(shared_card_ids))
        else:
            base = base.where(or_(Card.owner_id == user.id, Card.id.in_(shared_card_ids)))

        if favorite:
            fav_ids = (
                select(Favorite.card_id).where(Favorite.user_id == user.id).scalar_subquery()
            )
            base = base.where(Card.id.in_(fav_ids))

        if tag_id:
            tag_card_ids = (
                select(CardTag.card_id).where(CardTag.tag_id == tag_id).scalar_subquery()
            )
            base = base.where(Card.id.in_(tag_card_ids))

        if q:
            base = await apply_search(base, user.id, q)

    rows = list(await db.scalars(base))

    if ids:
        # ID 指定時は所有 or 共有受信のみ通す
        share_set = set(
            await db.scalars(
                select(CardShare.card_id).where(CardShare.shared_with == user.id)
            )
        )
        rows = [c for c in rows if c.owner_id == user.id or c.id in share_set]

    return rows


def _spreadsheet_cell(value: str) -> str:
    # Quoting CSV does not stop formulas. Prefix dangerous text for spreadsheet use.
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠")):
        return "'" + value
    return value


def _csv_bytes(cards: list[Card]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_COLUMNS)
    for c in cards:
        f = c.fields
        writer.writerow([_spreadsheet_cell((getattr(f, col, "") or "") if f else "") for col in CSV_COLUMNS])
    # Excel での文字化け回避に BOM を付ける
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _vcard_bytes(cards: list[Card]) -> bytes:
    out: list[str] = []
    for c in cards:
        f = c.fields
        if f is None:
            continue
        out.extend(_vcard_for(f))
    return "\r\n".join(out).encode("utf-8")


def _vesc(value: str | None) -> str:
    if not value:
        return ""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _vcard_for(f: CardField) -> list[str]:
    name = (f.person_name or "").strip()
    fn = name or (f.company or "")
    parts = name.split() if " " in name else (name.split("　") if "　" in name else [name])
    family = parts[0] if parts else ""
    given = parts[1] if len(parts) > 1 else ""

    lines = ["BEGIN:VCARD", "VERSION:3.0"]
    lines.append(f"FN:{_vesc(fn)}")
    lines.append(f"N:{_vesc(family)};{_vesc(given)};;;")
    if f.person_name_kana:
        lines.append(f"X-PHONETIC-FIRST-NAME:{_vesc(f.person_name_kana)}")
    if f.company or f.department:
        lines.append(f"ORG:{_vesc(f.company or '')};{_vesc(f.department or '')}")
    if f.title:
        lines.append(f"TITLE:{_vesc(f.title)}")
    if f.email:
        lines.append(f"EMAIL;TYPE=INTERNET:{_vesc(f.email)}")
    if f.phone:
        lines.append(f"TEL;TYPE=WORK,VOICE:{_vesc(f.phone)}")
    if f.mobile:
        lines.append(f"TEL;TYPE=CELL,VOICE:{_vesc(f.mobile)}")
    if f.fax:
        lines.append(f"TEL;TYPE=WORK,FAX:{_vesc(f.fax)}")
    if f.address or f.postal_code:
        lines.append(
            "ADR;TYPE=WORK:;;"
            f"{_vesc(f.address or '')};;;{_vesc(f.postal_code or '')};"
        )
    if f.website:
        lines.append(f"URL:{_vesc(f.website)}")
    lines.append("END:VCARD")
    return lines


@router.get("/cards")
async def export_cards(
    request: Request,
    format: Literal["csv", "vcard"] = Query("csv"),
    scope: Literal["owned", "shared", "all"] = Query("owned"),
    q: str | None = Query(None, max_length=200),
    favorite: bool = Query(False),
    tag_id: UUID | None = Query(None),
    ids: list[UUID] | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    cards = await _resolve_cards(
        db, user, scope=scope, q=q, favorite=favorite, tag_id=tag_id, ids=ids
    )
    if not cards:
        raise HTTPException(status_code=404, detail="no cards to export")

    if format == "csv":
        body = _csv_bytes(cards)
        media = "text/csv; charset=utf-8"
        filename = "cards.csv"
    else:
        body = _vcard_bytes(cards)
        media = "text/vcard; charset=utf-8"
        filename = "cards.vcf"

    await audit.record(
        db,
        user_id=user.id,
        action="card.export",
        request=request,
        target_type="card",
        metadata={"format": format, "count": len(cards), "scope": scope},
    )
    await db.commit()

    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
