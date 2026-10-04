"""PaddleOCR を呼び出して、生 OCR 結果（テキスト＋bbox）を返す。

PaddleOCR の初期化は重い（モデルロード〜数百MB）ので、プロセス起動時に1回だけ行う。
"""

from __future__ import annotations

import io
import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from threading import Lock

import cv2
import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

_ocr_lock = Lock()
_ocr_instance = None
_english_ocr_instance = None
_EMAIL_CANDIDATE_RE = re.compile(r"[A-Za-z0-9._%+\-]+\.[A-Za-z]{2,}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


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


def _get_english_ocr():
    global _english_ocr_instance
    if _english_ocr_instance is not None:
        return _english_ocr_instance
    with _ocr_lock:
        if _english_ocr_instance is None:
            from paddleocr import PaddleOCR

            _english_ocr_instance = PaddleOCR(
                lang="en", use_angle_cls=False, show_log=False, use_gpu=False,
            )
    return _english_ocr_instance


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


    @property
    def x_right(self) -> float:
        return max(p[0] for p in self.bbox)


def _shares_row(first: OcrLine, second: OcrLine) -> bool:
    shorter, taller = min(first.height, second.height), max(first.height, second.height)
    overlap = min(first.y_bottom, second.y_bottom) - max(first.y_top, second.y_top)
    return shorter > 0 and shorter >= 0.65 * taller and overlap >= 0.6 * shorter


def _merge_row_fragments(lines: list[OcrLine]) -> list[OcrLine]:
    """高さと縦方向の重なりが近い隣接領域を、左から右の1行へまとめる。"""
    rows: list[list[OcrLine]] = []
    for line in sorted(lines, key=lambda item: (item.y_top, item.x_left)):
        row = next(
            (group for group in rows if all(_shares_row(line, other) for other in group)),
            None,
        )
        if row is None:
            rows.append([line])
        else:
            row.append(line)

    result: list[OcrLine] = []
    for row in rows:
        fragments: list[OcrLine] = []
        for line in sorted(row, key=lambda item: item.x_left):
            if fragments:
                previous = fragments[-1]
                gap = line.x_left - previous.x_right
                if 0 <= gap <= 1.5 * min(line.height, previous.height):
                    top, bottom = min(previous.y_top, line.y_top), max(previous.y_bottom, line.y_bottom)
                    left, right = previous.x_left, line.x_right
                    fragments[-1] = OcrLine(
                        text=previous.text + " " + line.text,
                        confidence=min(previous.confidence, line.confidence),
                        bbox=[[left, top], [right, top], [right, bottom], [left, bottom]],
                        height=bottom - top,
                    )
                    continue
            fragments.append(line)
        result.extend(fragments)
    return sorted(result, key=lambda item: (item.y_top, item.x_left))


def _reread_email(line: OcrLine, image: np.ndarray) -> OcrLine:
    """メールらしいASCII領域を英語モデルで確認し、@を実認識できた場合のみ採用。"""
    text = unicodedata.normalize("NFKC", line.text).strip()
    if text.startswith("www.") or not _EMAIL_CANDIDATE_RE.fullmatch(text):
        return line
    padding = max(2, math.ceil(line.height * 0.25))
    h, w = image.shape[:2]
    x1, x2 = max(0, math.floor(line.x_left) - padding), min(w, math.ceil(line.x_right) + padding)
    y1, y2 = max(0, math.floor(line.y_top) - padding), min(h, math.ceil(line.y_bottom) + padding)
    crop = image[y1:y2, x1:x2]
    if not crop.size:
        return line
    try:
        recognized = _get_english_ocr().ocr(crop, det=False, cls=False)
        if recognized and recognized[0]:
            candidate, confidence = recognized[0][0]
            candidate = unicodedata.normalize("NFKC", candidate).strip()
            if confidence >= 0.8 and _EMAIL_RE.fullmatch(candidate):
                return OcrLine(candidate, float(confidence), line.bbox, line.height)
    except Exception:
        logger.warning("English email recognition failed; retaining Japanese result", exc_info=True)
    return line


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
    return _merge_row_fragments([_reread_email(line, img) for line in lines])
