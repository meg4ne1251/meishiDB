"""Limits shared by interactive and scanner uploads."""

import io
import warnings
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MAX_IMAGE_SIDE = 10_000
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


def validate_image(content: bytes) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
                if (
                    width * height > MAX_IMAGE_PIXELS
                    or max(width, height) > MAX_IMAGE_SIDE
                ):
                    raise HTTPException(
                        status_code=413, detail="image dimensions too large"
                    )
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise HTTPException(
                        status_code=400, detail="unsupported image format"
                    )
                image.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(status_code=413, detail="image dimensions too large")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HTTPException(status_code=400, detail="invalid image")


async def read_image(image: UploadFile, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="unsupported image type")
    content = bytearray()
    while chunk := await image.read(min(64 * 1024, max_bytes + 1 - len(content))):
        content.extend(chunk)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="image too large")
    if not content:
        raise HTTPException(status_code=400, detail="empty image")
    result = bytes(content)
    await run_in_threadpool(validate_image, result)
    return result
