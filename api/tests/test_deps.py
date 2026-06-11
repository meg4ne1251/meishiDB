"""セッション解決の依存（get_current_user / get_current_admin）の境界。"""

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.security import generate_session_token
from app.models.session import Session

COOKIE = get_settings().session_cookie_name


async def test_no_cookie_is_401(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "not authenticated"


async def test_invalid_session_token_is_401(client):
    client.cookies.set(COOKIE, "totally-bogus-token")
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid session"


async def test_expired_session_is_rejected_and_deleted(make_user, client_factory, db):
    _, user = await make_user(email="exp@example.com")

    # 期限切れセッションを直接差し込む
    token = generate_session_token()
    db.add(
        Session(
            id=token,
            user_id=user["id"],
            expires_at=datetime.now(tz=timezone.utc) - timedelta(days=1),
        )
    )
    await db.commit()

    c = client_factory()
    c.cookies.set(COOKIE, token)
    r = await c.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "session expired"

    # 期限切れセッションは削除される
    db.expire_all()
    assert await db.get(Session, token) is None


async def test_admin_only_endpoint_forbidden_for_member(make_user):
    # admin（先頭ユーザー）を先に作ってから member を作る
    await make_user(email="first-admin@example.com")
    member_client, _ = await make_user(email="member@example.com")

    r = await member_client.post("/api/search/reindex")
    assert r.status_code == 403
    assert r.json()["detail"] == "admin only"


async def test_admin_endpoint_allowed_for_admin(admin):
    admin_client, _ = admin
    r = await admin_client.post("/api/search/reindex")
    assert r.status_code == 200
    # Meilisearch 未設定なので configured=False
    assert r.json() == {"configured": False, "indexed": 0}
