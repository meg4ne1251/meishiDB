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


def test_contact_reread_joins_overlapping_email_fragments(monkeypatch):
    from app.pipeline import _reread_contacts
    class Recognizer:
        def ocr(self, image, **kwargs):
            assert image.shape[1] > 120
            return [[('E-mail: taro@example.com', .96)]]
    monkeypatch.setattr('app.pipeline._get_english_ocr', lambda: Recognizer())
    lines = [fragment('E-mail: tarogexam', 5, 5, width=90), fragment('ple.com', 85, 5, width=55)]
    result = _reread_contacts(lines, np.zeros((50, 200, 3), dtype=np.uint8))
    assert len(result) == 1
    assert result[0].text == 'E-mail: taro@example.com'
    assert result[0].x_right == 140


def test_contact_reread_low_confidence_keeps_fragments(monkeypatch):
    from app.pipeline import _reread_contacts
    class Recognizer:
        def ocr(self, image, **kwargs):
            return [[('taro@example.com', .6)]]
    monkeypatch.setattr('app.pipeline._get_english_ocr', lambda: Recognizer())
    lines = [fragment('E-mail: tarogexam', 5, 5, width=90), fragment('ple.com', 85, 5, width=55)]
    assert _reread_contacts(lines, np.zeros((50, 200, 3), dtype=np.uint8)) == lines


def test_orientation_fallback_selects_readable_card(monkeypatch):
    import app.pipeline as pipeline
    calls = []
    def recognize(ocr, image):
        calls.append(image.shape)
        if len(calls) == 2:
            return [fragment('株式会社テスト', 5, 5), fragment('山田 太郎', 5, 50, height=40)]
        return [fragment('???', 5, 5, confidence=.4)]
    monkeypatch.setattr(pipeline, '_get_ocr', lambda: object())
    monkeypatch.setattr(pipeline, '_recognize_lines', recognize)
    result = pipeline.run_ocr(_png_bytes(200, 120))
    assert [item.text for item in result] == ['株式会社テスト', '山田 太郎']
    assert len(calls) == 4


def test_upright_company_avoids_rotation_passes(monkeypatch):
    import app.pipeline as pipeline
    calls = []
    def recognize(ocr, image):
        calls.append(1)
        return [fragment('株式会社テスト', 5, 5)]
    monkeypatch.setattr(pipeline, '_get_ocr', lambda: object())
    monkeypatch.setattr(pipeline, '_recognize_lines', recognize)
    assert pipeline.run_ocr(_png_bytes(200, 120))[0].text == '株式会社テスト'
    assert len(calls) == 1


def test_english_contact_preserves_original_phone_separator(monkeypatch):
    from app.pipeline import _reread_contacts
    class Recognizer:
        def ocr(self, image, **kwargs):
            return [[('TEL:031234-5678', .95)]]
    monkeypatch.setattr('app.pipeline._get_english_ocr', lambda: Recognizer())
    original = fragment('TEL:03-1234-5678', 5, 5)
    result = _reread_contacts([original], np.zeros((50,200,3),dtype=np.uint8))
    assert result[0].text == 'TEL:03-1234-5678'


def test_english_contact_cannot_change_phone_digits(monkeypatch):
    from app.pipeline import _reread_contacts
    class Recognizer:
        def ocr(self, image, **kwargs):
            return [[('TEL:03-1234-5679', .99)]]
    monkeypatch.setattr('app.pipeline._get_english_ocr', lambda: Recognizer())
    original = fragment('TEL:03-1234-5678', 5, 5)
    assert _reread_contacts([original], np.zeros((50,200,3),dtype=np.uint8)) == [original]


@pytest.mark.parametrize("size", [(1, 10000), (10000, 1)])
def test_decode_narrow_image_keeps_nonzero_dimensions(size):
    image = io.BytesIO()
    Image.new("RGB", size, "white").save(image, format="PNG")
    decoded = _decode_image(image.getvalue())
    assert min(decoded.shape[:2]) == 1
    assert max(decoded.shape[:2]) == 2200
