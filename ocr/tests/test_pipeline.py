"""OcrLine の幾何プロパティと画像デコード。PaddleOCR 本体は重いので扱わない。"""

import io

import numpy as np
import pytest
from PIL import Image

from app.pipeline import OcrLine, _decode_image


def test_ocrline_geometry():
    ln = OcrLine(
        text="hello",
        confidence=0.9,
        bbox=[[10.0, 5.0], [50.0, 5.0], [50.0, 25.0], [10.0, 25.0]],
        height=20.0,
    )
    assert ln.y_top == 5.0
    assert ln.y_bottom == 25.0
    assert ln.x_left == 10.0


def _png_bytes(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_decode_image_returns_bgr_ndarray():
    arr = _decode_image(_png_bytes(120, 80))
    assert isinstance(arr, np.ndarray)
    # (height, width, 3) の BGR
    assert arr.shape == (80, 120, 3)


def test_decode_image_resizes_large_images():
    arr = _decode_image(_png_bytes(3000, 1000))
    # 長辺は 2200 以下に縮小される
    assert max(arr.shape[0], arr.shape[1]) <= 2200


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("paddleocr") is None,
    reason="paddleocr is not installed (heavy model dependency)",
)
def test_run_ocr_smoke():
    # PaddleOCR が入っている環境でのみ動かす軽いスモーク。
    from app.pipeline import run_ocr

    result = run_ocr(_png_bytes(200, 120))
    assert isinstance(result, list)
