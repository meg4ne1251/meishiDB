"""OCR サービス（PaddleOCR を内包する別コンテナ）への薄いプロキシ。

MVP M1 段階では呼び出し側はおらず、`call_ocr` は M2 で配線する。
"""

from typing import Any

import httpx

from app.core.config import get_settings


async def call_ocr(image_bytes: bytes) -> dict[str, Any]:
    """OCR サービスに画像を投げ、フィールド抽出結果を返す。"""
    settings = get_settings()
    url = settings.ocr_service_url.rstrip("/") + "/ocr"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, files={"image": ("card.jpg", image_bytes, "image/jpeg")})
        resp.raise_for_status()
        return resp.json()
