"""スキャナ watcher 用の image-import エンドポイント。

X-Scanner-Token ヘッダで認証し、設定された SCANNER_OWNER_EMAIL のユーザーを所有者として
名刺を作成 → MinIO に front 画像保存 → OCR → card_fields に書き込み。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.logging import log
from app.models.card import Card, CardField, OCR_FIELD_NAMES
from app.models.user import User
from app.schemas.card import CardDetail, CardFieldsRead
from app.services import audit, ocr_client, search_index, storage

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.post("/import", response_model=CardDetail)
async def import_scanned(
    request: Request,
    image: UploadFile = File(...),
    x_scanner_token: str | None = Header(default=None, alias="X-Scanner-Token"),
    db: AsyncSession = Depends(get_db),
) -> CardDetail:
    settings = get_settings()
    if not settings.scanner_api_token or not settings.scanner_owner_email:
        raise HTTPException(status_code=503, detail="scanner is not configured")
    if x_scanner_token != settings.scanner_api_token:
        raise HTTPException(status_code=401, detail="invalid scanner token")
    if not storage.is_configured():
        raise HTTPException(status_code=503, detail="storage is not configured")

    if image.content_type not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="unsupported image type")

    owner = await db.scalar(select(User).where(User.email == settings.scanner_owner_email))
    if owner is None:
        raise HTTPException(status_code=500, detail="scanner owner user not found")

    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty image")

    card = Card(owner_id=owner.id, source="scanner", status="ocr_running")
    db.add(card)
    await db.flush()

    field = CardField(card_id=card.id)
    db.add(field)

    try:
        original_key, _ = storage.upload_card_image(
            str(card.id), "front", content, image.content_type
        )
    except Exception as e:
        log.exception("storage.upload_failed", card_id=str(card.id))
        raise HTTPException(status_code=500, detail="storage upload failed")

    card.image_front_key = original_key
    await audit.record(
        db,
        user_id=owner.id,
        action="card.create",
        request=request,
        target_type="card",
        target_id=card.id,
        metadata={"source": "scanner"},
    )
    await db.commit()
    await db.refresh(card)
    card.fields = field

    try:
        result = await ocr_client.call_ocr(content)
        fields = result.get("fields") or {}
        for k, v in fields.items():
            if k in OCR_FIELD_NAMES and v and not getattr(field, k, None):
                setattr(field, k, v)
        field.raw_ocr_text = result.get("raw_text") or ""
        field.ocr_confidence = result.get("confidence") or {}
        card.status = "ocr_done"
        await db.commit()
        await db.refresh(card)
    except Exception as e:
        log.warning("scanner.ocr_failed", card_id=str(card.id), error=str(e))
        card.status = "uploaded"
        await db.commit()

    # 直前の db.refresh(card) で field が expire され得るので、シリアライズ前に読み直す。
    await db.refresh(field)

    await search_index.upsert_card(card, field)

    return CardDetail(
        id=card.id,
        owner_id=card.owner_id,
        status=card.status,
        source=card.source,
        image_front_key=card.image_front_key,
        image_back_key=card.image_back_key,
        created_at=card.created_at,
        updated_at=card.updated_at,
        fields=CardFieldsRead.model_validate(field),
        tags=[],
        is_favorite=False,
        shared=False,
    )
