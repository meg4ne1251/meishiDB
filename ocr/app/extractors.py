"""OCR 行から名刺フィールドを抽出。

正規表現＋位置ヒューリスティクスのみ。MVP として「うまく取れたら出す、取れなければ null」方針。
"""

from __future__ import annotations

import re
import unicodedata

from .pipeline import OcrLine

# --- 正規表現 ---

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"\b(?:https?://|www\.)[A-Za-z0-9./_\-?=&%#]+", re.IGNORECASE)
POSTAL_RE = re.compile(r"〒?\s?(\d{3})-?(\d{4})")
PHONE_RE = re.compile(r"(?:\+?81[-\s]?|0)\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}")
MOBILE_PREFIX = ("070", "080", "090")
FAX_HINT = re.compile(r"(?:FAX|Fax|fax|ＦＡＸ)", re.IGNORECASE)
TEL_HINT = re.compile(r"(?:TEL|Tel|tel|ＴＥＬ|電話)", re.IGNORECASE)
MOBILE_HINT = re.compile(r"(?:MOBILE|Mobile|携帯)", re.IGNORECASE)
ADDRESS_HINT = re.compile(
    r"(都|道|府|県|市|区|町|村|丁目|番地|番|号|[０-９0-9]+\-[０-９0-9]+)"
)
COMPANY_HINT = re.compile(r"(株式会社|有限会社|合同会社|合資会社|Co\.,?\s?Ltd\.?|Inc\.|Corporation|Corp\.|LLC)")
TITLE_HINT = re.compile(
    r"(部長|課長|係長|主任|社長|代表|取締役|専務|常務|部|室|課|チーム|マネージャー|"
    r"Manager|Director|Engineer|CEO|CTO|CFO|COO|President)"
)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _classify_phone(text: str) -> str:
    """phone / mobile / fax のいずれか。テキストから簡易判定。"""
    norm = _normalize(text)
    if FAX_HINT.search(norm):
        return "fax"
    if MOBILE_HINT.search(norm):
        return "mobile"
    digits_match = PHONE_RE.search(norm)
    if digits_match:
        digits = re.sub(r"\D", "", digits_match.group())
        if digits.startswith(MOBILE_PREFIX):
            return "mobile"
    return "phone"


def extract_fields(lines: list[OcrLine]) -> tuple[dict, dict, str]:
    """(fields, confidence, raw_text) を返す。"""
    fields: dict[str, str] = {}
    confidence: dict[str, float] = {}
    raw_text = "\n".join(l.text for l in lines)

    def set_field(key: str, value: str, conf: float) -> None:
        if key in fields:
            return
        fields[key] = value.strip()
        confidence[key] = round(conf, 3)

    # --- 単純 regex 系 ---
    for line in lines:
        norm = _normalize(line.text)

        # email
        m = EMAIL_RE.search(norm)
        if m:
            set_field("email", m.group(), line.confidence)

        # website
        m = URL_RE.search(norm)
        if m:
            url = m.group()
            if "@" not in url:  # email を URL と誤認しない
                set_field("website", url, line.confidence)

        # postal
        m = POSTAL_RE.search(norm)
        if m:
            set_field("postal_code", f"{m.group(1)}-{m.group(2)}", line.confidence)

        # phone / mobile / fax
        m = PHONE_RE.search(norm)
        if m:
            kind = _classify_phone(norm)
            set_field(kind, m.group(), line.confidence)

    # --- 会社名（上方の行＋"株式会社"等） ---
    for line in lines:
        norm = _normalize(line.text)
        if COMPANY_HINT.search(norm):
            set_field("company", norm, line.confidence)
            break

    # --- 役職 ---
    for line in lines:
        norm = _normalize(line.text)
        if TITLE_HINT.search(norm):
            set_field("title", norm, line.confidence)
            break

    # --- 住所（都道府県/市区町村/番地っぽい表記を含む長めの行） ---
    address_candidates = []
    for line in lines:
        norm = _normalize(line.text)
        if ADDRESS_HINT.search(norm) and len(norm) >= 8:
            # postal/email/url/phone と被らないように
            if EMAIL_RE.search(norm) or URL_RE.search(norm) or PHONE_RE.search(norm):
                continue
            address_candidates.append((norm, line.confidence))
    if address_candidates:
        # 一番長いものを採用（より具体的）
        addr, conf = max(address_candidates, key=lambda x: len(x[0]))
        set_field("address", addr, conf)

    # --- 氏名候補：高さ最大かつ短めで、会社/役職/住所/電話/email を含まない行 ---
    if lines and "person_name" not in fields:
        used_texts = {fields.get(k, "") for k in ("company", "title", "address")}
        scored = []
        for line in lines:
            norm = _normalize(line.text)
            if norm in used_texts:
                continue
            if (
                EMAIL_RE.search(norm)
                or URL_RE.search(norm)
                or PHONE_RE.search(norm)
                or POSTAL_RE.search(norm)
            ):
                continue
            if COMPANY_HINT.search(norm) or TITLE_HINT.search(norm):
                continue
            length = len(norm.replace(" ", "").replace("　", ""))
            if length < 2 or length > 14:
                continue
            scored.append((line.height, line.confidence, norm))
        if scored:
            scored.sort(key=lambda x: (-x[0], -x[1]))
            _, conf, name = scored[0]
            set_field("person_name", name, conf)

    return fields, confidence, raw_text
