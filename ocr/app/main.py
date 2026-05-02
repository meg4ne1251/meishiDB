"""PaddleOCR FastAPI サービス。`/ocr` 1 本。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile

from .extractors import extract_fields
from .pipeline import _get_ocr, run_ocr

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ocr")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時にモデルをロード（最初の推論で待たされないように）
    try:
        _get_ocr()
        logger.info("PaddleOCR ready")
    except Exception as e:
        logger.warning("PaddleOCR preload failed (will retry on first request): %s", e)
    yield


app = FastAPI(title="meishiDB OCR", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ocr")
async def ocr(image: UploadFile = File(...)) -> dict:
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="not an image")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="empty file")

    try:
        lines = run_ocr(image_bytes)
    except Exception as e:
        logger.exception("ocr failed")
        raise HTTPException(status_code=500, detail=f"ocr failed: {e}")

    fields, confidence, raw_text = extract_fields(lines)
    return {
        "raw_text": raw_text,
        "fields": fields,
        "confidence": confidence,
        "lines": [
            {"text": l.text, "confidence": l.confidence, "bbox": l.bbox} for l in lines
        ],
    }
