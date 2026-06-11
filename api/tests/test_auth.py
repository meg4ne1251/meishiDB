"""認証フロー（register / login / logout / me）と監査ログ。"""

from sqlalchemy import select

from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.session import Session
from app.models.user import User

COOKIE = get_settings().session_cookie_name


async def test_register_first_user_is_admin(client, db):
    r = await client.post(
        "/api/auth/register",
        json={"email": "first@example.com", "display_name": "First", "password": "password123"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "first@example.com"
    assert body["role"] == "admin"
    # セッション cookie が立つ
    assert COOKIE in r.cookies

    user = await db.scalar(select(User).where(User.email == "first@example.com"))
    assert user is not None
    # パスワードは平文で保存されない
    assert user.password_hash and user.password_hash != "password123"


async def test_second_user_is_member(client_factory):
    c1 = client_factory()
    r1 = await c1.post(
        "/api/auth/register",
        json={"email": "a@example.com", "display_name": "A", "password": "password123"},
    )
    assert r1.json()["role"] == "admin"

    c2 = client_factory()
    r2 = await c2.post(
        "/api/auth/register",
        json={"email": "b@example.com", "display_name": "B", "password": "password123"},
    )
    assert r2.status_code == 201
    assert r2.json()["role"] == "member"


async def test_register_duplicate_email_rejected(client_factory):
    c1 = client_factory()
    await c1.post(
        "/api/auth/register",
        json={"email": "dup@example.com", "display_name": "A", "password": "password123"},
    )
    c2 = client_factory()
    r = await c2.post(
        "/api/auth/register",
        json={"email": "dup@example.com", "display_name": "B", "password": "password123"},
    )
    assert r.status_code == 400
    assert "already registered" in r.json()["detail"]


async def test_register_email_is_case_insensitive(client_factory):
    """CITEXT なので大文字小文字違いは同一メールとして弾かれる。"""
    c1 = client_factory()
    await c1.post(
        "/api/auth/register",
        json={"email": "Case@example.com", "display_name": "A", "password": "password123"},
    )
    c2 = client_factory()
    r = await c2.post(
        "/api/auth/register",
        json={"email": "case@example.com", "display_name": "B", "password": "password123"},
    )
    assert r.status_code == 400


async def test_register_validation_errors(client):
    # password が短すぎる
    r = await client.post(
        "/api/auth/register",
        json={"email": "x@example.com", "display_name": "X", "password": "short"},
    )
    assert r.status_code == 422
    # email 形式が不正
    r = await client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "display_name": "X", "password": "password123"},
    )
    assert r.status_code == 422


async def test_login_success_and_records_audit(client_factory, db):
    c = client_factory()
    await c.post(
        "/api/auth/register",
        json={"email": "login@example.com", "display_name": "L", "password": "password123"},
    )
    # 別クライアントでログイン
    c2 = client_factory()
    r = await c2.post(
        "/api/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "login@example.com"
    assert COOKIE in r.cookies

    # last_login_at が入る
    user = await db.scalar(select(User).where(User.email == "login@example.com"))
    assert user.last_login_at is not None

    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "login" in actions


async def test_login_wrong_password(client_factory, db):
    c = client_factory()
    await c.post(
        "/api/auth/register",
        json={"email": "wp@example.com", "display_name": "L", "password": "password123"},
    )
    c2 = client_factory()
    r = await c2.post(
        "/api/auth/login", json={"email": "wp@example.com", "password": "wrongpass1"}
    )
    assert r.status_code == 401
    assert COOKIE not in r.cookies

    actions = (await db.scalars(select(AuditLog.action))).all()
    assert "login_failed" in actions


async def test_login_unknown_email(client, db):
    r = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "password123"}
    )
    assert r.status_code == 401
    # ユーザー不明でも login_failed は記録される（user_id は NULL）
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "login_failed"))
    assert row is not None
    assert row.user_id is None


async def test_me_requires_auth(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_returns_current_user(make_user):
    c, user = await make_user(email="me@example.com")
    r = await c.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "me@example.com"
    assert r.json()["id"] == user["id"]


async def test_logout_deletes_session(make_user, db):
    c, user = await make_user(email="lo@example.com")
    # ログイン中はセッションが存在
    sessions = (await db.scalars(select(Session).where(Session.user_id == user["id"]))).all()
    assert len(sessions) == 1

    r = await c.post("/api/auth/logout")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    db.expire_all()
    sessions = (await db.scalars(select(Session).where(Session.user_id == user["id"]))).all()
    assert sessions == []

    # cookie が消えたので me は 401
    r2 = await c.get("/api/auth/me")
    assert r2.status_code == 401
