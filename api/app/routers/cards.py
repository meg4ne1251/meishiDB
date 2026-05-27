from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal, get_db
from app.core.logging import log
from app.deps import get_current_user
from app.models.card import Card, CardField, CardShare, CardTag, Favorite
from app.models.tag import Tag
from app.models.user import User
from app.schemas.card import (
    CardCreate,
    CardDetail,
    CardFieldsRead,
    CardGeoPoint,
    CardGeoResponse,
    CardListResponse,
    CardSummary,
    CardUpdate,
    ShareInfo,
    ShareRequest,
    TagSummary,
)
from app.services import audit, geocoder, ocr_client, search_index, storage

router = APIRouter(prefix="/cards", tags=["cards"])

# 地図に一度に返すマーカー数の上限。これを超える規模ではクラスタリング等が必要だが、
# まずは描画が破綻しないよう新しい順に上限件数で打ち切る。
GEO_MAX_POINTS = 5000


CARD_STATUSES = {"uploaded", "ocr_running", "ocr_done", "confirmed", "archived"}
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 15 MB


async def _resolve_tags(db: AsyncSession, owner_id: UUID, tag_ids: list[UUID]) -> list[Tag]:
    if not tag_ids:
        return []
    result = await db.scalars(
        select(Tag).where(Tag.owner_id == owner_id, Tag.id.in_(tag_ids))
    )
    tags = list(result)
    if len(tags) != len(set(tag_ids)):
        raise HTTPException(status_code=400, detail="some tags do not belong to user")
    return tags


async def _serialize(
    db: AsyncSession, card: Card, *, viewer_id: UUID, shared: bool = False
) -> CardSummary:
    tag_rows = await db.execute(
        select(Tag)
        .join(CardTag, CardTag.tag_id == Tag.id)
        .where(CardTag.card_id == card.id)
        .order_by(Tag.name)
    )
    tags = [TagSummary.model_validate(t) for t in tag_rows.scalars()]

    is_fav = (
        await db.scalar(
            select(Favorite.user_id).where(
                Favorite.user_id == viewer_id, Favorite.card_id == card.id
            )
        )
    ) is not None

    return CardSummary(
        id=card.id,
        owner_id=card.owner_id,
        status=card.status,
        source=card.source,
        image_front_key=card.image_front_key,
        image_back_key=card.image_back_key,
        created_at=card.created_at,
        updated_at=card.updated_at,
        fields=CardFieldsRead.model_validate(card.fields) if card.fields else None,
        tags=tags,
        is_favorite=is_fav,
        shared=shared,
    )


async def _geocode_card_in_background(card_id: UUID) -> None:
    """住所から座標を補完する（best-effort）。レスポンス送出後に別セッションで実行する。

    ジオコーダ呼び出しは遅い（自前 Nominatim で数百ms〜数秒）ため、作成/更新の
    リクエスト処理をブロックしないようバックグラウンドで動かす。リクエストの
    DB セッションは応答後に閉じているので、ここで専用のセッションを開く。
    未設定・住所なし・失敗時は黙って何もしない。
    """
    if not geocoder.is_configured():
        return
    async with SessionLocal() as db:
        card = await db.scalar(
            select(Card).options(selectinload(Card.fields)).where(Card.id == card_id)
        )
        if card is None or card.fields is None:
            return
        address = card.fields.address
        if not address or not address.strip():
            return
        coords = await geocoder.geocode(address)
        if coords is None:
            return
        card.fields.latitude, card.fields.longitude = coords
        card.fields.geocoded_at = datetime.now(timezone.utc)
        await db.commit()


async def _ensure_access(
    db: AsyncSession, card_id: UUID, user: User, *, need_edit: bool = False
) -> tuple[Card, bool]:
    card = await db.scalar(
        select(Card)
        .options(selectinload(Card.fields))
        .where(Card.id == card_id)
    )
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")

    if card.owner_id == user.id:
        return card, False

    share = await db.scalar(
        select(CardShare).where(
            CardShare.card_id == card_id, CardShare.shared_with == user.id
        )
    )
    if share is None:
        raise HTTPException(status_code=404, detail="card not found")
    if need_edit and share.permission != "edit":
        raise HTTPException(status_code=403, detail="read-only share")

    return card, True


@router.get("", response_model=CardListResponse)
async def list_cards(
    request: Request,
    scope: Literal["owned", "shared", "all"] = Query("owned"),
    q: str | None = Query(default=None, max_length=200),
    favorite: bool = Query(default=False),
    tag_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CardListResponse:
    """名刺一覧。q が指定された場合は Meilisearch を優先、未配線時は Postgres ILIKE。"""

    base = (
        select(Card)
        .options(selectinload(Card.fields))
        .order_by(Card.updated_at.desc())
    )

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
        tag_card_ids = select(CardTag.card_id).where(CardTag.tag_id == tag_id).scalar_subquery()
        base = base.where(Card.id.in_(tag_card_ids))

    if q:
        # Meilisearch が動いていれば、まず ID 集合に絞り込む
        meili_ids = await search_index.search_card_ids(user.id, q)
        if meili_ids is not None:
            if not meili_ids:
                return CardListResponse(items=[], total=0)
            base = base.where(Card.id.in_(meili_ids))
        else:
            like = f"%{q}%"
            base = base.join(CardField, CardField.card_id == Card.id, isouter=True).where(
                or_(
                    CardField.person_name.ilike(like),
                    CardField.person_name_kana.ilike(like),
                    CardField.company.ilike(like),
                    CardField.department.ilike(like),
                    CardField.title.ilike(like),
                    CardField.email.ilike(like),
                    CardField.phone.ilike(like),
                    CardField.mobile.ilike(like),
                    CardField.address.ilike(like),
                )
            )

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = await db.scalars(base.limit(limit).offset(offset))

    items: list[CardSummary] = []
    for c in rows:
        items.append(await _serialize(db, c, viewer_id=user.id, shared=c.owner_id != user.id))

    return CardListResponse(items=items, total=total)


@router.post("", response_model=CardDetail, status_code=status.HTTP_201_CREATED)
async def create_card(
    payload: CardCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CardDetail:
    tags = await _resolve_tags(db, user.id, payload.tag_ids)

    status_value = "confirmed" if payload.source == "manual" else "uploaded"
    card = Card(owner_id=user.id, source=payload.source, status=status_value)
    db.add(card)
    await db.flush()

    field = CardField(card_id=card.id, **payload.fields.model_dump())
    db.add(field)

    for t in tags:
        db.add(CardTag(card_id=card.id, tag_id=t.id))

    await audit.record(
        db,
        user_id=user.id,
        action="card.create",
        request=request,
        target_type="card",
        target_id=card.id,
    )
    await db.commit()
    await db.refresh(card)
    card.fields = field

    if geocoder.is_configured():
        background_tasks.add_task(_geocode_card_in_background, card.id)

    summary = await _serialize(db, card, viewer_id=user.id)
    await search_index.upsert_card(card, field)
    return CardDetail(**summary.model_dump())


@router.get("/geo", response_model=CardGeoResponse)
async def list_card_geo(
    scope: Literal["owned", "shared", "all"] = Query("owned"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CardGeoResponse:
    """座標を持つ名刺だけを地図表示用に返す軽量エンドポイント。"""
    shared_card_ids = (
        select(CardShare.card_id).where(CardShare.shared_with == user.id).scalar_subquery()
    )

    stmt = (
        select(Card, CardField)
        .join(CardField, CardField.card_id == Card.id)
        .where(CardField.latitude.isnot(None), CardField.longitude.isnot(None))
    )
    if scope == "owned":
        stmt = stmt.where(Card.owner_id == user.id)
    elif scope == "shared":
        stmt = stmt.where(Card.id.in_(shared_card_ids))
    else:
        stmt = stmt.where(or_(Card.owner_id == user.id, Card.id.in_(shared_card_ids)))

    stmt = stmt.order_by(Card.created_at.desc()).limit(GEO_MAX_POINTS)
    rows = await db.execute(stmt)
    items = [
        CardGeoPoint(
            id=card.id,
            person_name=f.person_name,
            company=f.company,
            address=f.address,
            latitude=f.latitude,
            longitude=f.longitude,
            shared=card.owner_id != user.id,
        )
        for card, f in rows.all()
    ]
    return CardGeoResponse(items=items)


@router.get("/{card_id}", response_model=CardDetail)
async def get_card(
    card_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CardDetail:
    card, shared = await _ensure_access(db, card_id, user)

    await audit.record(
        db,
        user_id=user.id,
        action="card.view",
        request=request,
        target_type="card",
        target_id=card.id,
    )
    await db.commit()

    summary = await _serialize(db, card, viewer_id=user.id, shared=shared)
    return CardDetail(**summary.model_dump())


@router.patch("/{card_id}", response_model=CardDetail)
async def update_card(
    card_id: UUID,
    payload: CardUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CardDetail:
    card, shared = await _ensure_access(db, card_id, user, need_edit=True)

    if payload.status is not None:
        if payload.status not in CARD_STATUSES:
            raise HTTPException(status_code=400, detail="invalid status")
        card.status = payload.status

    should_geocode = False
    if payload.fields is not None:
        if card.fields is None:
            card.fields = CardField(card_id=card.id)
            db.add(card.fields)
        changes = payload.fields.model_dump(exclude_unset=True)
        address_changed = "address" in changes and changes["address"] != card.fields.address
        for k, v in changes.items():
            setattr(card.fields, k, v)
        # 古い座標を無効化するのはジオコーダが有効なとき「だけ」。
        # 無効時に消すと再取得できず、地図に出ていた名刺が復旧手段なく消えてしまう。
        if address_changed and geocoder.is_configured():
            should_geocode = True
            card.fields.latitude = None
            card.fields.longitude = None
            card.fields.geocoded_at = None

    if payload.tag_ids is not None:
        if shared:
            raise HTTPException(status_code=403, detail="tags are managed by the owner")
        tags = await _resolve_tags(db, user.id, payload.tag_ids)
        await db.execute(delete(CardTag).where(CardTag.card_id == card.id))
        for t in tags:
            db.add(CardTag(card_id=card.id, tag_id=t.id))

    await audit.record(
        db,
        user_id=user.id,
        action="card.update",
        request=request,
        target_type="card",
        target_id=card.id,
        metadata={"shared": shared},
    )
    await db.commit()
    await db.refresh(card)

    if should_geocode:
        background_tasks.add_task(_geocode_card_in_background, card.id)

    summary = await _serialize(db, card, viewer_id=user.id, shared=shared)
    await search_index.upsert_card(card, card.fields)
    return CardDetail(**summary.model_dump())


@router.delete("/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(
    card_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    card = await db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")
    if card.owner_id != user.id:
        raise HTTPException(status_code=403, detail="only owner can delete")

    await db.delete(card)
    await audit.record(
        db,
        user_id=user.id,
        action="card.delete",
        request=request,
        target_type="card",
        target_id=card_id,
    )
    await db.commit()

    if storage.is_configured():
        try:
            storage.delete_card_images(str(card_id))
        except Exception as e:
            log.warning("storage.delete_failed", card_id=str(card_id), error=str(e))
    await search_index.delete_card(card_id)


# ---------------- 画像アップロード ----------------


@router.post("/{card_id}/image", response_model=CardDetail)
async def upload_card_image(
    card_id: UUID,
    request: Request,
    side: Literal["front", "back"] = Form("front"),
    run_ocr: bool = Form(True),
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CardDetail:
    """名刺画像をアップロード。front の場合は OCR を起動してフィールドを上書き。"""
    if not storage.is_configured():
        raise HTTPException(status_code=503, detail="storage is not configured")

    card, shared = await _ensure_access(db, card_id, user, need_edit=True)
    if shared:
        raise HTTPException(status_code=403, detail="only owner can upload images")

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="unsupported image type")

    content = await image.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="empty image")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="image too large")

    try:
        original_key, _thumb_key = storage.upload_card_image(
            str(card.id), side, content, image.content_type
        )
    except Exception as e:
        log.exception("storage.upload_failed")
        raise HTTPException(status_code=500, detail=f"storage upload failed: {e}")

    if side == "front":
        card.image_front_key = original_key
        if run_ocr:
            card.status = "ocr_running"
    else:
        card.image_back_key = original_key

    await audit.record(
        db,
        user_id=user.id,
        action="card.image_upload",
        request=request,
        target_type="card",
        target_id=card.id,
        metadata={"side": side, "size": len(content)},
    )
    await db.commit()
    await db.refresh(card)

    if side == "front" and run_ocr:
        try:
            result = await ocr_client.call_ocr(content)
        except Exception as e:
            log.warning("ocr.failed", card_id=str(card.id), error=str(e))
            card.status = "uploaded"
            await db.commit()
        else:
            await _apply_ocr_result(db, card, result)

    summary = await _serialize(db, card, viewer_id=user.id)
    await search_index.upsert_card(card, card.fields)
    return CardDetail(**summary.model_dump())


@router.get("/{card_id}/image")
async def get_card_image(
    card_id: UUID,
    side: Literal["front", "back"] = Query("front"),
    thumb: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    card, _ = await _ensure_access(db, card_id, user)
    key = card.image_front_key if side == "front" else card.image_back_key
    if not key:
        raise HTTPException(status_code=404, detail="image not found")

    if thumb and side == "front":
        thumb_key = key.rsplit(".", 1)[0] + "_512.webp"
        try:
            data, ct = storage.get_card_image(thumb_key, thumb=True)
        except Exception:
            data, ct = storage.get_card_image(key)
    else:
        try:
            data, ct = storage.get_card_image(key)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"image not found: {e}")

    return Response(content=data, media_type=ct, headers={"Cache-Control": "private, max-age=300"})


@router.post("/{card_id}/ocr", response_model=CardDetail)
async def rerun_ocr(
    card_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CardDetail:
    """既にアップロード済みの front 画像で OCR を再実行する。"""
    if not storage.is_configured():
        raise HTTPException(status_code=503, detail="storage is not configured")

    card, shared = await _ensure_access(db, card_id, user, need_edit=True)
    if shared:
        raise HTTPException(status_code=403, detail="only owner can rerun ocr")
    if not card.image_front_key:
        raise HTTPException(status_code=400, detail="no front image uploaded")

    try:
        data, _ = storage.get_card_image(card.image_front_key)
        result = await ocr_client.call_ocr(data)
    except Exception as e:
        log.warning("ocr.rerun_failed", card_id=str(card.id), error=str(e))
        raise HTTPException(status_code=502, detail=f"ocr failed: {e}")

    await _apply_ocr_result(db, card, result)
    await audit.record(
        db,
        user_id=user.id,
        action="card.ocr",
        request=request,
        target_type="card",
        target_id=card.id,
    )
    await db.commit()
    await db.refresh(card)

    summary = await _serialize(db, card, viewer_id=user.id)
    await search_index.upsert_card(card, card.fields)
    return CardDetail(**summary.model_dump())


@router.post("/{card_id}/geocode", response_model=CardDetail)
async def geocode_card(
    card_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CardDetail:
    """カードの住所を再ジオコーディングして座標を更新する。"""
    if not geocoder.is_configured():
        raise HTTPException(status_code=503, detail="geocoder is not configured")

    card, shared = await _ensure_access(db, card_id, user, need_edit=True)
    address = (card.fields.address if card.fields else None) or ""
    if not address.strip():
        raise HTTPException(status_code=400, detail="no address to geocode")

    coords = await geocoder.geocode(address)
    if coords is None:
        raise HTTPException(status_code=404, detail="address could not be geocoded")

    card.fields.latitude, card.fields.longitude = coords
    card.fields.geocoded_at = datetime.now(timezone.utc)

    await audit.record(
        db,
        user_id=user.id,
        action="card.geocode",
        request=request,
        target_type="card",
        target_id=card.id,
    )
    await db.commit()
    await db.refresh(card)

    summary = await _serialize(db, card, viewer_id=user.id, shared=shared)
    return CardDetail(**summary.model_dump())


async def _apply_ocr_result(db: AsyncSession, card: Card, result: dict) -> None:
    """OCR の出力（{fields, confidence, raw_text}）を card_fields に適用。"""
    fields = result.get("fields") or {}
    confidence = result.get("confidence") or {}
    raw_text = result.get("raw_text") or ""

    if card.fields is None:
        card.fields = CardField(card_id=card.id)
        db.add(card.fields)

    for k, v in fields.items():
        if v and not getattr(card.fields, k, None):
            setattr(card.fields, k, v)

    card.fields.raw_ocr_text = raw_text
    card.fields.ocr_confidence = confidence
    card.status = "ocr_done"
    await db.commit()
    await db.refresh(card)


# ---------------- favorites / share ----------------


@router.post("/{card_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
async def add_favorite(
    card_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _ensure_access(db, card_id, user)
    exists = await db.scalar(
        select(Favorite.card_id).where(Favorite.user_id == user.id, Favorite.card_id == card_id)
    )
    if exists is None:
        db.add(Favorite(user_id=user.id, card_id=card_id))
        await db.commit()


@router.delete("/{card_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    card_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    fav = await db.get(Favorite, (user.id, card_id))
    if fav is not None:
        await db.delete(fav)
        await db.commit()


@router.get("/{card_id}/shares", response_model=list[ShareInfo])
async def list_shares(
    card_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ShareInfo]:
    card = await db.get(Card, card_id)
    if card is None or card.owner_id != user.id:
        raise HTTPException(status_code=404, detail="card not found")
    rows = await db.scalars(select(CardShare).where(CardShare.card_id == card_id))
    return [ShareInfo.model_validate(r) for r in rows]


@router.post("/{card_id}/shares", response_model=ShareInfo, status_code=status.HTTP_201_CREATED)
async def create_share(
    card_id: UUID,
    payload: ShareRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShareInfo:
    card = await db.get(Card, card_id)
    if card is None or card.owner_id != user.id:
        raise HTTPException(status_code=404, detail="card not found")

    target = await db.scalar(select(User).where(User.email == payload.user_email))
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="cannot share with yourself")

    existing = await db.scalar(
        select(CardShare).where(
            CardShare.card_id == card_id, CardShare.shared_with == target.id
        )
    )
    if existing is not None:
        existing.permission = payload.permission
        share = existing
    else:
        share = CardShare(
            card_id=card_id,
            shared_by=user.id,
            shared_with=target.id,
            permission=payload.permission,
        )
        db.add(share)
        await db.flush()

    await audit.record(
        db,
        user_id=user.id,
        action="card.share",
        request=request,
        target_type="card",
        target_id=card_id,
        metadata={"shared_with": str(target.id), "permission": payload.permission},
    )
    await db.commit()
    await db.refresh(share)
    await _sync_shares_to_search(db, card_id)
    return ShareInfo.model_validate(share)


@router.delete("/{card_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_share(
    card_id: UUID,
    share_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    share = await db.get(CardShare, share_id)
    if share is None or share.card_id != card_id:
        raise HTTPException(status_code=404, detail="share not found")
    card = await db.get(Card, card_id)
    if card is None or card.owner_id != user.id:
        raise HTTPException(status_code=403, detail="only owner can revoke")
    await db.delete(share)
    await db.commit()
    await _sync_shares_to_search(db, card_id)


async def _sync_shares_to_search(db: AsyncSession, card_id: UUID) -> None:
    rows = await db.scalars(
        select(CardShare.shared_with).where(CardShare.card_id == card_id)
    )
    await search_index.update_shares(card_id, list(rows))
