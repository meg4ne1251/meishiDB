"""OcrLine の幾何プロパティと画像デコード。PaddleOCR 本体は重いので扱わない。"""

import io

import numpy as np
import pytest
from PIL import Image

from app.pipeline import OcrLine, _decode_image, _merge_row_fragments, _reread_email


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


def fragment(text, x, y, width=80, height=30, confidence=0.9):
    return OcrLine(
        text, confidence,
        [[x, y], [x + width, y], [x + width, y + height], [x, y + height]], height,
    )


def test_split_name_is_merged_left_to_right_despite_y_jitter():
    lines = _merge_row_fragments([
        fragment("太郎", 100, 99, confidence=0.98),
        fragment("山田", 10, 100, confidence=0.95),
        fragment("開発部", 10, 200),
        fragment("部長", 100, 201),
    ])
    assert [line.text for line in lines] == ["山田 太郎", "開発部 部長"]
    assert lines[0].confidence == 0.95
    from app.extractors import extract_fields
    fields, _, raw = extract_fields(lines)
    assert fields["person_name"] == "山田 太郎"
    assert fields["title"] == "開発部 部長"
    assert raw == "山田 太郎\n開発部 部長"


@pytest.mark.parametrize("second", [
    fragment("別列", 300, 100),
    fragment("次行", 100, 140),
    fragment("小さい文字", 100, 100, height=10),
    fragment("重複領域", 50, 100),
])
def test_unrelated_text_is_not_merged(second):
    lines = _merge_row_fragments([fragment("山田", 10, 100), second])
    assert len(lines) == 2


def test_existing_line_is_preserved():
    line = fragment("山田 太郎", 10, 100)
    assert _merge_row_fragments([line]) == [line]


@pytest.mark.parametrize("text", ["taro@example.com", "株式会社テスト", "www.example.com", "https://example.com"])
def test_email_fallback_does_not_reinterpret_known_text(text, monkeypatch):
    def unexpected():
        pytest.fail("English model must not be loaded for this text")
    monkeypatch.setattr("app.pipeline._get_english_ocr", unexpected)
    line = fragment(text, 5, 5)
    assert _reread_email(line, np.zeros((50, 100, 3), dtype=np.uint8)) is line


@pytest.mark.parametrize("recognized, confidence, expected", [
    ("taro@example.com", 0.95, "taro@example.com"),
    ("tarogexample.com", 0.99, "tarogexample.com"),
    ("taro@example.com", 0.5, "tarogexample.com"),
])
def test_email_fallback_requires_recognized_at_sign_and_confidence(recognized, confidence, expected, monkeypatch):
    class Recognizer:
        def ocr(self, image, *, det, cls):
            assert det is False and cls is False
            assert image.size
            return [[(recognized, confidence)]]
    monkeypatch.setattr("app.pipeline._get_english_ocr", lambda: Recognizer())
    original = fragment("tarogexample.com", 5, 5)
    result = _reread_email(original, np.zeros((50, 100, 3), dtype=np.uint8))
    assert result.text == expected
    assert result.bbox == original.bbox


def test_email_fallback_failure_keeps_original_result(monkeypatch):
    def unavailable():
        raise RuntimeError("model unavailable")
    monkeypatch.setattr("app.pipeline._get_english_ocr", unavailable)
    original = fragment("tarogexample.com", 5, 5)
    assert _reread_email(original, np.zeros((50, 100, 3), dtype=np.uint8)) is original


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("paddleocr") is None,
    reason="paddleocr is not installed (heavy model dependency)",
)
def test_run_ocr_smoke():
    # PaddleOCR が入っている環境でのみ動かす軽いスモーク。
    from app.pipeline import run_ocr

    result = run_ocr(_png_bytes(200, 120))
    assert isinstance(result, list)
