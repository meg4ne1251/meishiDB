"""名刺フィールド抽出（正規表現＋位置ヒューリスティクス）。"""

import pytest

from app.extractors import _classify_phone, _normalize, extract_fields
from app.pipeline import OcrLine


def line(text: str, *, confidence: float = 0.9, height: float = 10.0) -> OcrLine:
    """テスト用 OcrLine。bbox は height を反映した矩形にする。"""
    bbox = [[0.0, 0.0], [100.0, 0.0], [100.0, height], [0.0, height]]
    return OcrLine(text=text, confidence=confidence, bbox=bbox, height=height)


# ----------------------------- _normalize / _classify_phone -----------------------------


def test_normalize_fullwidth_to_halfwidth():
    assert _normalize("ＴＥＬ：０３") == "TEL:03"
    assert _normalize("  spaced  ") == "spaced"


def test_classify_phone_plain():
    assert _classify_phone("TEL: 03-1234-5678") == "phone"
    assert _classify_phone("03-1234-5678") == "phone"


def test_classify_phone_fax_hint():
    assert _classify_phone("FAX: 03-1234-5678") == "fax"
    assert _classify_phone("ＦＡＸ 03-1234-5678") == "fax"


def test_classify_phone_mobile_hint_and_prefix():
    assert _classify_phone("携帯 080-1111-2222") == "mobile"
    assert _classify_phone("090-1234-5678") == "mobile"


# ----------------------------- extract_fields -----------------------------


def test_extract_email():
    fields, conf, _ = extract_fields([line("taro@example.com")])
    assert fields["email"] == "taro@example.com"
    assert "email" in conf


def test_extract_website_but_not_email():
    fields, _, _ = extract_fields(
        [line("https://example.com/path"), line("info@example.com")]
    )
    assert fields["website"] == "https://example.com/path"
    # email を website に誤分類しない
    assert fields["email"] == "info@example.com"


def test_extract_postal_code_formatting():
    fields, _, _ = extract_fields([line("〒123-4567")])
    assert fields["postal_code"] == "123-4567"
    # ハイフン無しでも整形される
    fields2, _, _ = extract_fields([line("1234567")])
    assert fields2["postal_code"] == "123-4567"


def test_extract_phone_mobile_fax_separately():
    fields, _, _ = extract_fields(
        [
            line("TEL 03-1234-5678"),
            line("FAX 03-1234-9999"),
            line("携帯 090-1111-2222"),
        ]
    )
    assert fields["phone"] == "03-1234-5678"
    assert fields["fax"] == "03-1234-9999"
    assert fields["mobile"] == "090-1111-2222"


@pytest.mark.parametrize(
    "text",
    [
        "TEL 03-1234-5678",
        "09012345678",
        "011 1234567",
        "+81-3-1234-5678",
        "ＦＡＸ ０３－１２３４－５６７８",
    ],
)
def test_phone_is_not_extracted_as_postal_code(text):
    fields, _, _ = extract_fields([line(text)])
    assert "postal_code" not in fields
    assert any(key in fields for key in ("phone", "mobile", "fax"))


def test_postal_code_and_phone_on_same_line():
    fields, _, _ = extract_fields([line("〒100-0001 TEL 03-1234-5678")])
    assert fields["postal_code"] == "100-0001"
    assert fields["phone"] == "03-1234-5678"


def test_extract_company():
    fields, _, _ = extract_fields([line("株式会社テストカンパニー")])
    assert fields["company"] == "株式会社テストカンパニー"


def test_extract_title():
    fields, _, _ = extract_fields([line("営業部 部長")])
    assert fields["title"] == "営業部 部長"


def test_extract_address_picks_longest():
    fields, _, _ = extract_fields(
        [
            line("東京都港区"),
            line("東京都港区六本木一丁目二番三号"),
        ]
    )
    assert fields["address"] == "東京都港区六本木一丁目二番三号"


def test_extract_person_name_by_height():
    fields, _, _ = extract_fields(
        [
            line("山田太郎", height=40),
            line("株式会社テスト", height=20),
            line("部長", height=15),
            line("東京都港区六本木一丁目", height=10),
        ]
    )
    assert fields["person_name"] == "山田太郎"
    assert fields["company"] == "株式会社テスト"
    assert fields["title"] == "部長"


def test_first_match_wins_for_duplicate_keys():
    fields, _, _ = extract_fields(
        [line("first@example.com"), line("second@example.com")]
    )
    assert fields["email"] == "first@example.com"


def test_raw_text_is_joined_lines():
    _, _, raw = extract_fields([line("行1"), line("行2"), line("行3")])
    assert raw == "行1\n行2\n行3"


def test_empty_input():
    fields, conf, raw = extract_fields([])
    assert fields == {}
    assert conf == {}
    assert raw == ""


@pytest.mark.parametrize('text, expected', [
    ('TEL (03) 1234-5678', '03 1234-5678'),
    ('TEL 03（1234）5678', '0312345678'),
    ('TEL 03−1234−5678', '03-1234-5678'),
])
def test_phone_notation_variants(text, expected):
    fields, _, _ = extract_fields([line(text)])
    assert fields['phone'] == expected
    assert 'postal_code' not in fields


def test_shared_contact_row():
    fields, _, _ = extract_fields([line('TEL:03-1234-5678 FAX:03-1234-9999 MOBILE:+81-90-1234-5678')])
    assert fields['phone'] == '03-1234-5678'
    assert fields['fax'] == '03-1234-9999'
    assert fields['mobile'] == '+81-90-1234-5678'


def test_spaced_email_punctuation():
    fields, _, _ = extract_fields([line('E-mail: taro @ example . com')])
    assert fields['email'] == 'taro@example.com'


@pytest.mark.parametrize('company', ['(株)東京商事', '医療法人山田医院', 'ACME ltd.', 'Example INC'])
def test_company_variants_do_not_become_title_or_name(company):
    fields, _, _ = extract_fields([line(company, height=40), line('山田 太郎', height=25)])
    assert fields['company'] == company
    assert fields['person_name'] == '山田 太郎'
    assert 'title' not in fields


def test_explicit_name_label():
    fields, _, _ = extract_fields([line('CREATIVE', height=60), line('氏名: 山田 太郎')])
    assert fields['person_name'] == '山田 太郎'


def test_address_postal_and_building_continuation():
    from app.pipeline import OcrLine
    def row(text, x, y):
        return OcrLine(text, .95, [[x,y],[x+200,y],[x+200,y+20],[x,y+20]],20)
    fields, _, _ = extract_fields([
        row('〒100-0001 東京都千代田区丸の内1-1-1',0,100),
        row('丸の内ビル 8F',0,125), row('別のビル 2F',400,125),
        row('山田 太郎',0,20),
    ])
    assert fields['address'] == '東京都千代田区丸の内1-1-1 丸の内ビル 8F'
    assert fields['postal_code'] == '100-0001'
    assert fields['person_name'] == '山田 太郎'


def test_corrupted_postal_prefix_excluded_from_address_without_guessing():
    fields, _, _ = extract_fields([line('F100-00ø1 東京都千代田区丸の内1-1-1')])
    assert fields['address'] == '東京都千代田区丸の内1-1-1'
    assert 'postal_code' not in fields


def test_lowercase_english_title():
    fields, _, _ = extract_fields([line('software engineer'), line('John Smith', height=30), line('Acme Ltd.')])
    assert fields['title'] == 'software engineer'
    assert fields['person_name'] == 'John Smith'


@pytest.mark.parametrize('name', ['服部 太郎', '小室 花子', 'Alexander Montgomery', 'Jean-Pierre Dupont'])
def test_surnames_and_long_latin_names(name):
    fields, _, _ = extract_fields([line(name, height=40), line('営業部', height=20)])
    assert fields['person_name'] == name
    assert fields['title'] == '営業部'


def test_long_vowel_before_floor_number_is_preserved():
    assert _normalize('タワー8F') == 'タワー8F'
    assert _normalize('03ー1234ー5678') == '03-1234-5678'
