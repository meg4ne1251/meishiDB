"""MinIO (S3 互換) アクセスのラッパー。

- アプリ起動時に必要なバケットを作成する `ensure_buckets()`
- 画像アップロード／取得／削除
- サムネイル生成（front のみ、Pillow で 512px の WebP）
"""

from __future__ import annotations

import io
import logging
from uuid import uuid4

from PIL import Image, ImageOps

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client = None


def _is_configured() -> bool:
    s = get_settings()
    return bool(s.minio_endpoint and s.minio_access_key and s.minio_secret_key)


def get_client():
    """boto3 ではなく minio-py を使う（依存が軽い）。"""
    global _client
    if _client is not None:
        return _client
    if not _is_configured():
        raise RuntimeError("MinIO is not configured")
    import urllib3
    from minio import Minio

    s = get_settings()
    endpoint = s.minio_endpoint
    secure = endpoint.startswith("https://")
    host = endpoint.replace("https://", "").replace("http://", "")
    _client = Minio(
        host,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=secure,
        http_client=urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=5.0, read=30.0),
            retries=urllib3.Retry(total=2, backoff_factor=0.2),
            maxsize=10,
        ),
    )
    return _client


def ensure_buckets() -> None:
    if not _is_configured():
        logger.info("MinIO not configured; skipping bucket bootstrap")
        return
    client = get_client()
    s = get_settings()
    for bucket in (s.minio_bucket_original, s.minio_bucket_thumb):
        try:
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
                logger.info("created MinIO bucket: %s", bucket)
        except Exception as e:
            logger.warning("bucket bootstrap failed for %s: %s", bucket, e)


def _put(bucket: str, key: str, data: bytes, content_type: str) -> None:
    client = get_client()
    client.put_object(
        bucket,
        key,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def upload_card_image(
    card_id: str, side: str, content: bytes, content_type: str
) -> tuple[str, str | None]:
    """名刺画像（オリジナル＋サムネ）を保存して、(original_key, thumb_key) を返す。"""
    if side not in ("front", "back"):
        raise ValueError("side must be front or back")
    if not _is_configured():
        raise RuntimeError("MinIO is not configured")

    s = get_settings()
    ext = _ext_for(content_type)
    # Each upload is immutable: delayed OCR/readers must refer to the bytes
    # they started with, and a failed replacement must not show an old thumbnail.
    image_name = f"{side}-{uuid4().hex}"
    original_key = f"{card_id}/{image_name}.{ext}"
    _put(s.minio_bucket_original, original_key, content, content_type)

    thumb_key: str | None = None
    if side == "front":
        try:
            thumb_bytes = _make_thumbnail(content)
            thumb_key = f"{card_id}/{image_name}_512.webp"
            _put(s.minio_bucket_thumb, thumb_key, thumb_bytes, "image/webp")
        except Exception as e:
            logger.warning("thumbnail generation failed: %s", e)

    return original_key, thumb_key


def get_card_image(side_key: str, *, thumb: bool = False) -> tuple[bytes, str]:
    """画像を MinIO から取得して (bytes, content_type) を返す。"""
    if not _is_configured():
        raise RuntimeError("MinIO is not configured")
    s = get_settings()
    bucket = s.minio_bucket_thumb if thumb else s.minio_bucket_original
    client = get_client()
    resp = client.get_object(bucket, side_key)
    try:
        data = resp.read()
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        return data, content_type
    finally:
        resp.close()
        resp.release_conn()


def delete_card_images(card_id: str) -> None:
    if not _is_configured():
        return
    s = get_settings()
    client = get_client()
    for bucket in (s.minio_bucket_original, s.minio_bucket_thumb):
        try:
            objects = client.list_objects(bucket, prefix=f"{card_id}/", recursive=True)
            for obj in objects:
                client.remove_object(bucket, obj.object_name)
        except Exception as e:
            logger.warning("delete images failed (%s/%s): %s", bucket, card_id, e)


def _ext_for(content_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/heic": "heic",
    }.get(content_type, "bin")


def _make_thumbnail(content: bytes, max_side: int = 512) -> bytes:
    img = Image.open(io.BytesIO(content))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue()


def is_configured() -> bool:
    return _is_configured()
