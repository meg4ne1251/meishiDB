"""OCR サービス（PaddleOCR を内包する別コンテナ）への薄いプロキシ。

画像アップロード・再実行・スキャナ取り込みで同じ同時呼び出し制限を使用する。
"""

import asyncio
from typing import Annotated, Any

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.schemas.card import CardFieldsBase
from app.schemas.text import DatabaseText

_OCR_SEMAPHORE = asyncio.Semaphore(5)


class OCRResult(BaseModel):
    """Validate service output before it can modify a database transaction."""

    fields: CardFieldsBase = Field(default_factory=CardFieldsBase)
    raw_text: DatabaseText = ""
    confidence: dict[DatabaseText, Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]] = Field(
        default_factory=dict
    )


async def call_ocr(image_bytes: bytes) -> dict[str, Any]:
    """OCR サービスに画像を投げ、フィールド抽出結果を返す。"""
    settings = get_settings()
    url = settings.ocr_service_url.rstrip("/") + "/ocr"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, files={"image": ("card.jpg", image_bytes, "image/jpeg")})
        resp.raise_for_status()
        return resp.json()


async def call_ocr_limited(image_bytes: bytes) -> dict[str, Any]:
    try:
        await asyncio.wait_for(_OCR_SEMAPHORE.acquire(), timeout=5.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="OCR is busy; retry later")
    try:
        result = await call_ocr(image_bytes)
        try:
            return OCRResult.model_validate(result).model_dump()
        except ValidationError:
            # Callers log the exception; do not include private OCR text in it.
            raise ValueError("invalid OCR response") from None
    finally:
        _OCR_SEMAPHORE.release()
