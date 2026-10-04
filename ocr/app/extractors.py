"""OCR 行から名刺フィールドを抽出。

表記の正規化、連絡先ラベル、領域の位置を使って名刺フィールドを抽出。
"""

from __future__ import annotations

import re
import unicodedata

from .pipeline import OcrLine

# --- 正規表現 ---

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"\b(?:https?://|www\.)[A-Za-z0-9./_\-?=&%#]+", re.IGNORECASE)
POSTAL_RE = re.compile(r"(?<![\d-])〒?\s?(\d{3})-?(\d{4})(?![\d-])")
PHONE_RE = re.compile(
    r"(?<![\d-])(?:\+?81[-\s()]*(?:\d[-\s()]*){8,9}\d|0[-\s()]*(?:\d[-\s()]*){8,9}\d)(?![\d-])"
)
MOBILE_PREFIX = ("070", "080", "090")
FAX_HINT = re.compile(r"(?:FAX|Fax|fax|ＦＡＸ)", re.IGNORECASE)
TEL_HINT = re.compile(r"(?:TEL|Tel|tel|ＴＥＬ|電話)", re.IGNORECASE)
MOBILE_HINT = re.compile(r"(?:MOBILE|Mobile|携帯)", re.IGNORECASE)
ADDRESS_HINT = re.compile(
    r"(都|道|府|県|市|区|町|村|丁目|番地|番|号|[０-９0-9]+\-[０-９0-9]+)"
)
COMPANY_HINT = re.compile(r"(株式会社|有限会社|合同会社|合資会社|一般社団法人|公益財団法人|医療法人|学校法人|\(株\)|\(有\)|Co\.,?\s?Ltd\.?|Inc\.?\b|Corporation|Corp\.?\b|LLC\b|Ltd\.?\b)", re.IGNORECASE)
TITLE_HINT = re.compile(
    r"(部長|課長|係長|主任|社長|代表|取締役|専務|常務|(?:営業|開発|技術|総務|人事|経理|企画|研究|広報|販売|事業|情報|管理|製造|品質|保証|生産|設計|マーケティング)[一-龥ァ-ヶA-Za-z]*[部室課]|チーム|マネージャー|"
    r"Manager|Director|Engineer|CEO|CTO|CFO|COO|President|デザイナー|弁護士|税理士|教授|医師)",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip()
    return re.sub(r"(?<=\d)[‐‑‒–—−ー](?=\d)", "-", text)


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
        if digits.startswith(MOBILE_PREFIX) or digits.startswith(("8170", "8180", "8190")):
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
        # Spaces around actual email punctuation are common in OCR. Never invent @.
        contact = re.sub(r"\s*([@.])\s*", r"\1", norm)

        # email
        m = EMAIL_RE.search(contact)
        if m:
            set_field("email", m.group(), line.confidence)

        # website
        m = URL_RE.search(norm)
        if m:
            url = m.group()
            if "@" not in url:  # email を URL と誤認しない
                set_field("website", url, line.confidence)

        # postal
        # 電話番号の一部を郵便番号として拾わない。
        m = POSTAL_RE.search(PHONE_RE.sub(" ", norm))
        if m:
            set_field("postal_code", f"{m.group(1)}-{m.group(2)}", line.confidence)

        # phone / mobile / fax
        previous_end = 0
        for m in PHONE_RE.finditer(norm):
            # Associate each number with its own preceding label on a shared row.
            prefix = norm[previous_end:m.start()]
            labels = list(re.finditer(r"FAX|TEL|MOBILE|携帯|電話", prefix, re.IGNORECASE))
            hint = labels[-1].group() if labels else ""
            kind = _classify_phone(hint + " " + m.group())
            value = re.sub(r"[()]", "", m.group()).strip()
            set_field(kind, value, line.confidence)
            previous_end = m.end()

    # --- 会社名（上方の行＋"株式会社"等） ---
    for line in lines:
        norm = _normalize(line.text)
        if COMPANY_HINT.search(norm):
            set_field("company", norm, line.confidence)
            break

    # --- 役職 ---
    for line in lines:
        norm = _normalize(line.text)
        if TITLE_HINT.search(norm) and not COMPANY_HINT.search(norm) and not EMAIL_RE.search(norm) and not URL_RE.search(norm) and not PHONE_RE.search(norm):
            set_field("title", norm, line.confidence)
            break

    # --- 住所（都道府県/市区町村/番地っぽい表記を含む長めの行） ---
    address_candidates = []
    for line in lines:
        norm = _normalize(line.text)
        prefecture = re.search(r"東京都|北海道|京都府|大阪府|[一-龥]{2,3}県", norm)
        if prefecture and re.search(r"\d", norm[:prefecture.start()]):
            # A corrupted postal prefix must not contaminate the street address.
            norm = norm[prefecture.start():]
        norm = POSTAL_RE.sub("", norm).strip(" 〒,:")
        # Damaged contact numbers still must not become the street address.
        if re.match(r"^(?:TEL|FAX|MOBILE|E[- ]?mail|電話|携帯)\s*[:：]", norm, re.IGNORECASE):
            continue
        if COMPANY_HINT.search(norm) or TITLE_HINT.search(norm) or norm == fields.get("company"):
            continue
        if ADDRESS_HINT.search(norm) and len(norm) >= 8:
            # postal/email/url/phone と被らないように
            if EMAIL_RE.search(norm) or URL_RE.search(norm) or PHONE_RE.search(norm):
                continue
            address_candidates.append((norm, line.confidence, line))
    if address_candidates:
        # 一番長いものを採用（より具体的）
        addr, conf, anchor = max(address_candidates, key=lambda x: len(x[0]))
        # Join nearby aligned continuation rows (building/floor), never another column.
        for following in sorted(lines, key=lambda item: item.y_top):
            gap = following.y_top - anchor.y_bottom
            value = _normalize(following.text)
            if not (0 <= gap <= 1.5 * anchor.height and abs(following.x_left - anchor.x_left) <= 2 * anchor.height):
                continue
            if not re.search(r"ビル|マンション|タワー|階|\d\s*[FＦ]\b", value):
                continue
            if COMPANY_HINT.search(value) or EMAIL_RE.search(value) or URL_RE.search(value) or PHONE_RE.search(value):
                continue
            addr += " " + value
            conf = min(conf, following.confidence)
            anchor = following
        set_field("address", addr, conf)

    # --- 氏名候補：高さ最大かつ短めで、会社/役職/住所/電話/email を含まない行 ---
    if lines and "person_name" not in fields:
        used_texts = {fields.get(k, "") for k in ("company", "title", "address")}
        scored = []
        for line in lines:
            norm = _normalize(line.text)
            explicit = re.match(r"^(?:氏名|名前|Name)\s*[:：]\s*(.+)$", norm, re.IGNORECASE)
            if explicit:
                set_field("person_name", explicit.group(1), line.confidence)
                break
            if norm in used_texts or ADDRESS_HINT.search(norm) and len(norm) >= 8:
                continue
            if re.search(r"〒|ビル|マンション|タワー|\d\s*F\b", norm):
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
            limit = 40 if re.fullmatch(r"[A-Za-zÀ-ÿ.'’\-]+(?:\s+[A-Za-zÀ-ÿ.'’\-]+)+", norm) else 14
            if length < 2 or length > limit:
                continue
            scored.append((line.height, line.confidence, norm))
        if scored and "person_name" not in fields:
            scored.sort(key=lambda x: (-x[0], -x[1]))
            _, conf, name = scored[0]
            set_field("person_name", name, conf)

    return fields, confidence, raw_text
