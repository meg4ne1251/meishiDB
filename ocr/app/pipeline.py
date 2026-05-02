"""PaddleOCR を呼び出して、生 OCR 結果（テキスト＋bbox）を返す。

PaddleOCR の初期化は重い（モデルロード〜数百MB）ので、プロセス起動時に1回だけ行う。
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from threading import Lock

import cv2
import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_ocr_lock = Lock()
_ocr_instance = None


def _get_ocr():
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance
    with _ocr_lock:
        if _ocr_instance is None:
            from paddleocr import PaddleOCR

            logger.info("loading PaddleOCR (PP-OCRv4 server, CPU)")
            _ocr_instance = PaddleOCR(
                lang="japan",
                use_angle_cls=True,
                show_log=False,
                use_gpu=False,
            )
    return _ocr_instance


@dataclass
class OcrLine:
    text: str
    confidence: float
    bbox: list[list[float]]  # 4 点 (x,y)
    height: float

    @property
    def y_top(self) -> float:
        return min(p[1] for p in self.bbox)

    @property
    def y_bottom(self) -> float:
        return max(p[1] for p in self.bbox)

    @property
    def x_left(self) -> float:
        return min(p[0] for p in self.bbox)


def _decode_image(image_bytes: bytes) -> np.ndarray:
    """bytes → BGR ndarray。EXIF 回転を尊重し、巨大画像はリサイズして OCR を安定させる。"""
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img).convert("RGB")

    max_side = 2200
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    arr = np.array(img)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def run_ocr(image_bytes: bytes) -> list[OcrLine]:
    """PaddleOCR を実行して行ごとのテキスト＋bbox を返す。"""
    ocr = _get_ocr()
    img = _decode_image(image_bytes)

    raw = ocr.ocr(img, cls=True)
    if not raw or not raw[0]:
        return []

    lines: list[OcrLine] = []
    for entry in raw[0]:
        bbox, (text, conf) = entry
        if not text or not text.strip():
            continue
        ys = [p[1] for p in bbox]
        height = max(ys) - min(ys)
        lines.append(
            OcrLine(text=text.strip(), confidence=float(conf), bbox=bbox, height=float(height))
        )
    # 上から順
    lines.sort(key=lambda l: l.y_top)
    return lines
