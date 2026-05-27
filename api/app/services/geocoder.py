"""住所 → 緯度経度のジオコーディング。

セルフホスト純度を保つため、外部 SaaS ではなく自前で建てた Nominatim
(または Nominatim 互換 API) を `GEOCODER_URL` で指す前提。未設定の場合は
すべて no-op（`geocode` は None を返す）で、地図機能は座標を持つ名刺のみ表示する。

Nominatim は OSM 抽出データのインポートが必要で重いため、デフォルト無効。
`deploy/docker-compose.yml` の `geocoder` プロファイルで任意起動できる。
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(get_settings().geocoder_url)


async def geocode(address: str) -> tuple[float, float] | None:
    """住所文字列を (latitude, longitude) に変換する。失敗時は None。

    Nominatim の `/search` エンドポイント（`format=jsonv2`）を想定。
    """
    settings = get_settings()
    if not settings.geocoder_url or not address or not address.strip():
        return None

    url = settings.geocoder_url.rstrip("/") + "/search"
    params = {
        "q": address.strip(),
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "jp",
    }
    headers = {"User-Agent": settings.geocoder_user_agent}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            results = resp.json()
        if not results:
            return None
        first = results[0]
        lat, lon = float(first["lat"]), float(first["lon"])
        # 互換 API を差し替えられる前提なので範囲を健全性チェックする。
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            logger.warning("geocode returned out-of-range coords for %r: %s, %s", address, lat, lon)
            return None
        return lat, lon
    except Exception as e:
        logger.warning("geocode failed for %r: %s", address, e)
        return None
