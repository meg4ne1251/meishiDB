"""PaddleOCR FastAPI サービス。`/ocr` 1 本。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from .body_limit import BodyLimitMiddleware
from .images import read_image

from .extractors import extract_fields
from .pipeline import _get_ocr, run_ocr

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("ocr")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時にモデルをロード（最初の推論で待たされないように）
    try:
        await run_in_threadpool(_get_ocr)
        logger.info("PaddleOCR ready")
    except Exception as e:
        logger.warning("PaddleOCR preload failed (will retry on first request): %s", e)
    yield


app = FastAPI(title="meishiDB OCR", version="0.1.0", lifespan=lifespan)
app.add_middleware(BodyLimitMiddleware)
_INFERENCE_SLOT = asyncio.Semaphore(1)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ocr")
async def ocr(image: UploadFile = File(...)) -> dict:
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="not an image")

    image_bytes = await read_image(image)
    try:
        await asyncio.wait_for(_INFERENCE_SLOT.acquire(), timeout=5.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="OCR is busy; retry later")
    try:
        # PaddleOCR's shared model is used by one thread at a time.
        def infer():
            lines = run_ocr(image_bytes)
            return lines, extract_fields(lines)

        lines, (fields, confidence, raw_text) = await run_in_threadpool(infer)
    except Exception:
        logger.exception("ocr failed")
        raise HTTPException(status_code=500, detail="ocr failed")
    finally:
        _INFERENCE_SLOT.release()

    return {
        "raw_text": raw_text,
        "fields": fields,
        "confidence": confidence,
        "lines": [
            {"text": line.text, "confidence": line.confidence, "bbox": line.bbox} for line in lines
        ],
    }
