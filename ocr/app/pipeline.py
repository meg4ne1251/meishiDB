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
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    arr = np.array(img)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _recognize_lines(ocr, img: np.ndarray) -> list[OcrLine]:
    raw = ocr.ocr(img, cls=True)
    lines = []
    for bbox, (text, conf) in (raw[0] if raw and raw[0] else []):
        if text and text.strip():
            height = max(p[1] for p in bbox) - min(p[1] for p in bbox)
            lines.append(OcrLine(text.strip(), float(conf), bbox, float(height)))
    return lines


def _reread_contacts(lines: list[OcrLine], img: np.ndarray) -> list[OcrLine]:
    """Re-read ASCII contact rows, including overlapping email detections.

    Accept only actual recognized contact syntax at high confidence. Failed
    recognition keeps all original fragments, without speculative corrections.
    """
    result = []
    remaining = list(lines)
    while remaining:
        line = remaining.pop(0)
        norm = unicodedata.normalize("NFKC", line.text)
        if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", norm):
            result.append(_reread_email(line, img))
            continue
        is_email = bool(re.search(r"e[- ]?mail|@", norm, re.IGNORECASE))
        is_phone = bool(re.search(r"(?:\d[- ()]*){9,}", norm))
        if not (is_email or is_phone):
            result.append(_reread_email(line, img))
            continue
        group = [line]
        if is_email:
            # Detector boxes can overlap in the middle of an email address.
            for other in remaining:
                if (_shares_row(line, other)
                    and -line.height <= other.x_left - max(item.x_right for item in group) <= 1.5 * line.height
                    and other.x_left >= line.x_left
                    and re.fullmatch(r"[A-Za-z0-9.@_+%\- ]+", other.text)):
                    group.append(other)
        left, right = min(item.x_left for item in group), max(item.x_right for item in group)
        top, bottom = min(item.y_top for item in group), max(item.y_bottom for item in group)
        pad = max(2, math.ceil(line.height * .25))
        h, w = img.shape[:2]
        crop = img[max(0,math.floor(top)-pad):min(h,math.ceil(bottom)+pad),
                   max(0,math.floor(left)-pad):min(w,math.ceil(right)+pad)]
        replacement = None
        try:
            recognized = _get_english_ocr().ocr(crop, det=False, cls=False) if crop.size else None
            if recognized and recognized[0]:
                text, conf = recognized[0][0]
                text = unicodedata.normalize("NFKC", text).strip()
                from .extractors import PHONE_RE
                valid = _EMAIL_RE.search(text) if is_email else PHONE_RE.search(text)
                if conf >= .8 and valid:
                    if is_phone:
                        # Preserve already recognized numbers and their separators;
                        # use English to repair labels, never overwrite a different number.
                        original_numbers = list(PHONE_RE.finditer(norm))
                        new_numbers = list(PHONE_RE.finditer(text))
                        if len(original_numbers) != len(new_numbers) or any(
                            re.sub(r"\D", "", first.group()) != re.sub(r"\D", "", second.group())
                            for first, second in zip(original_numbers, new_numbers)
                        ):
                            result.append(line)
                            continue
                        for first, second in reversed(list(zip(original_numbers, new_numbers))):
                            text = text[:second.start()] + first.group() + text[second.end():]
                    replacement = OcrLine(text, float(conf),
                        [[left,top],[right,top],[right,bottom],[left,bottom]], bottom-top)
        except Exception:
            logger.warning("Contact recognition failed; retaining original text", exc_info=True)
        if replacement:
            remaining = [other for other in remaining if all(other is not item for item in group[1:])]
            result.append(replacement)
        else:
            result.append(line)
    return result


def _orientation_score(lines: list[OcrLine]) -> float:
    from .extractors import extract_fields
    fields, confidence, _ = extract_fields(lines)
    # Identity words help distinguish upright text from confidently read digits.
    identities = sum(confidence.get(key, 0) for key in ("company", "title"))
    vertical_penalty = 6 * sum(line.height > 1.5 * (line.x_right - line.x_left) for line in lines) / max(1, len(lines))
    company_rows = [line for line in lines if fields.get("company") == line.text]
    contacts = [line for line in lines if re.search(r"@|(?:\d[- ()]*){9,}", line.text)]
    inverted_penalty = 3 if company_rows and contacts and company_rows[0].y_top > max(line.y_top for line in contacts) else 0
    return identities * 4 + sum(confidence.values()) - vertical_penalty - inverted_penalty + sum(
        min(len(line.text), 40) * line.confidence for line in lines if line.confidence >= .8
    ) / 100


def run_ocr(image_bytes: bytes) -> list[OcrLine]:
    """Recognize text; bboxes refer to the resized, orientation-corrected image."""
    ocr = _get_ocr()
    img = _decode_image(image_bytes)
    lines = _recognize_lines(ocr, img)
    from .extractors import extract_fields
    fields, confidence, _ = extract_fields(_merge_row_fragments(lines))
    tall_boxes = sum(line.height > 1.5 * (line.x_right - line.x_left) for line in lines)
    company_rows = [line for line in lines if fields.get("company") == line.text]
    contact_rows = [line for line in lines if re.search(r"@|(?:\d[- ()]*){9,}", line.text)]
    inverted_layout = bool(company_rows and contact_rows and
        company_rows[0].y_top > max(line.y_top for line in contact_rows))
    if (tall_boxes > len(lines) / 3 or inverted_layout or
        not any(confidence.get(key, 0) >= .85 for key in ("company", "title"))):
        best_score = _orientation_score(lines)
        original = img
        for turns in (1, 2, 3):
            candidate_image = np.ascontiguousarray(np.rot90(original, turns))
            candidate = _recognize_lines(ocr, candidate_image)
            score = _orientation_score(candidate)
            if score > best_score + .5:
                lines, img, best_score = candidate, candidate_image, score
    return _merge_row_fragments(_reread_contacts(lines, img))
