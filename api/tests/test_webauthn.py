"""パスキー (WebAuthn) のチャレンジ管理とエンドポイント分岐。

実際の認証器が無いと verify_* は通せないので、ここでは「成功手前までの分岐」
（未認証・challenge 期限切れ・ユーザー不一致・未知クレデンシャル等）を検証する。
"""

import base64
import time

import pytest
from fastapi import HTTPException

from app.routers import webauthn as wa


# ----------------------------- challenge ヘルパ -----------------------------


def test_save_and_pop_challenge_roundtrip():
    cid = wa._save_challenge(b"some-challenge-bytes", "user-123")
    challenge, uid = wa._pop_challenge(cid)
    assert challenge == b"some-challenge-bytes"
    assert uid == "user-123"
    # 一度 pop したら消える
    with pytest.raises(HTTPException) as exc:
        wa._pop_challenge(cid)
    assert exc.value.status_code == 400


def test_pop_missing_challenge_raises():
    with pytest.raises(HTTPException) as exc:
        wa._pop_challenge("does-not-exist")
    assert exc.value.status_code == 400
    assert "expired or missing" in exc.value.detail


def test_pop_expired_challenge_raises():
    cid = "expired-cid"
    wa._CHALLENGES[cid] = ("YWJj", "user-1", time.time() - 1)
    with pytest.raises(HTTPException) as exc:
        wa._pop_challenge(cid)
    assert exc.value.status_code == 400
    assert "expired" in exc.value.detail


def test_gc_removes_expired_only():
    wa._CHALLENGES.clear()
    wa._CHALLENGES["old"] = ("x", None, time.time() - 100)
    wa._CHALLENGES["fresh"] = ("y", None, time.time() + 100)
    wa._gc_challenges()
    assert "old" not in wa._CHALLENGES
    assert "fresh" in wa._CHALLENGES


# ----------------------------- registration -----------------------------


async def test_register_begin_requires_auth(client):
    r = await client.post("/api/webauthn/register/begin")
    assert r.status_code == 401


async def test_register_begin_returns_options(make_user):
    c, _ = await make_user()
    r = await c.post("/api/webauthn/register/begin")
    assert r.status_code == 200
    body = r.json()
    assert "challenge_id" in body
    assert "challenge" in body["options"]
    assert body["options"]["rp"]["id"] == "localhost"


async def test_register_finish_missing_fields(make_user):
    c, _ = await make_user()
    r = await c.post("/api/webauthn/register/finish", json={})
    assert r.status_code == 400
    assert "required" in r.json()["detail"]


async def test_register_finish_unknown_challenge(make_user):
    c, _ = await make_user()
    r = await c.post(
        "/api/webauthn/register/finish",
        json={"challenge_id": "nope", "credential": {"x": 1}},
    )
    assert r.status_code == 400
    assert "expired or missing" in r.json()["detail"]


async def test_register_finish_user_mismatch(make_user):
    c1, _ = await make_user(email="wa1@example.com")
    c2, _ = await make_user(email="wa2@example.com")
    begin = (await c1.post("/api/webauthn/register/begin")).json()
    # c1 が作った challenge を c2 が使う → ユーザー不一致
    r = await c2.post(
        "/api/webauthn/register/finish",
        json={"challenge_id": begin["challenge_id"], "credential": {"x": 1}},
    )
    assert r.status_code == 400
    assert "user mismatch" in r.json()["detail"]


async def test_list_credentials_empty(make_user):
    c, _ = await make_user()
    r = await c.get("/api/webauthn/credentials")
    assert r.status_code == 200
    assert r.json() == []


async def test_delete_unknown_credential_404(make_user):
    c, _ = await make_user()
    r = await c.delete("/api/webauthn/credentials/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


# ----------------------------- authentication -----------------------------


async def test_login_begin_returns_options_without_email(client):
    r = await client.post("/api/webauthn/login/begin", json={})
    assert r.status_code == 200
    body = r.json()
    assert "challenge_id" in body
    assert "challenge" in body["options"]


async def test_login_begin_with_unknown_email_does_not_leak(client):
    # 未知のメールでもエラーにせず options を返す（存在リーク防止）
    r = await client.post("/api/webauthn/login/begin", json={"email": "ghost@example.com"})
    assert r.status_code == 200


async def test_login_finish_missing_fields(client):
    r = await client.post("/api/webauthn/login/finish", json={})
    assert r.status_code == 400


async def test_login_finish_unknown_credential(client):
    begin = (await client.post("/api/webauthn/login/begin", json={})).json()
    raw_id = base64.urlsafe_b64encode(b"nonexistent-credential").decode().rstrip("=")
    r = await client.post(
        "/api/webauthn/login/finish",
        json={"challenge_id": begin["challenge_id"], "credential": {"rawId": raw_id}},
    )
    assert r.status_code == 401
    assert "unknown credential" in r.json()["detail"]
