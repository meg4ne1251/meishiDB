"""CSV / vCard エクスポート。"""

import csv
import io

from sqlalchemy import select

from app.models.audit import AuditLog


async def _create_card(client, **fields):
    r = await client.post("/api/cards", json={"source": "manual", "fields": fields})
    assert r.status_code == 201, r.text
    return r.json()


async def test_export_csv_basic(make_user):
    c, _ = await make_user()
    await _create_card(
        c, person_name="山田太郎", company="テスト商事", email="t@example.com"
    )
    r = await c.get("/api/export/cards", params={"format": "csv"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert "cards.csv" in r.headers["content-disposition"]

    # BOM 付き
    assert r.content.startswith(b"\xef\xbb\xbf")
    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][:3] == ["person_name", "person_name_kana", "company"]
    data = rows[1]
    assert data[0] == "山田太郎"
    assert data[2] == "テスト商事"


async def test_export_default_format_is_csv(make_user):
    c, _ = await make_user()
    await _create_card(c, person_name="A")
    r = await c.get("/api/export/cards")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")


async def test_export_vcard(make_user):
    c, _ = await make_user()
    await _create_card(
        c,
        person_name="山田 太郎",
        company="テスト商事",
        title="部長",
        email="t@example.com",
        phone="03-1234-5678",
    )
    r = await c.get("/api/export/cards", params={"format": "vcard"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/vcard")
    body = r.content.decode("utf-8")
    assert "BEGIN:VCARD" in body
    assert "VERSION:3.0" in body
    assert "FN:山田 太郎" in body
    assert "N:山田;太郎;;;" in body
    assert "ORG:テスト商事;" in body
    assert "TITLE:部長" in body
    assert "EMAIL;TYPE=INTERNET:t@example.com" in body
    assert "END:VCARD" in body


async def test_export_vcard_escapes_special_chars(make_user):
    c, _ = await make_user()
    await _create_card(c, person_name="姓", company="A;B,C")
    r = await c.get("/api/export/cards", params={"format": "vcard"})
    body = r.content.decode("utf-8")
    # ; と , はエスケープされる
    assert r"A\;B\,C" in body


async def test_export_empty_is_404(make_user):
    c, _ = await make_user()
    r = await c.get("/api/export/cards", params={"format": "csv"})
    assert r.status_code == 404


async def test_export_records_audit(make_user, db):
    c, user = await make_user()
    await _create_card(c, person_name="A")
    await c.get("/api/export/cards", params={"format": "csv"})
    row = await db.scalar(
        select(AuditLog).where(
            AuditLog.user_id == user["id"], AuditLog.action == "card.export"
        )
    )
    assert row is not None
    assert row.audit_metadata["format"] == "csv"
    assert row.audit_metadata["count"] == 1


async def test_export_favorite_filter(make_user):
    c, _ = await make_user()
    fav = await _create_card(c, person_name="fav")
    await _create_card(c, person_name="nofav")
    await c.post(f"/api/cards/{fav['id']}/favorite")
    r = await c.get("/api/export/cards", params={"format": "csv", "favorite": "true"})
    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 2  # header + 1
    assert rows[1][0] == "fav"


async def test_export_by_ids_enforces_access(make_user):
    c1, _ = await make_user(email="ex1@example.com")
    c2, _ = await make_user(email="ex2@example.com")
    mine = await _create_card(c1, person_name="mine")
    theirs = await _create_card(c2, person_name="theirs")

    # c1 が自分のと他人の id を両方指定 → 自分のだけ出る
    r = await c1.get(
        "/api/export/cards", params={"format": "csv", "ids": [mine["id"], theirs["id"]]}
    )
    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 2
    assert rows[1][0] == "mine"


async def test_export_requires_auth(client):
    r = await client.get("/api/export/cards")
    assert r.status_code == 401
