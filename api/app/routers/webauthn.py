"""パスキー (WebAuthn) 登録／認証エンドポイント。

ライブラリは `py_webauthn` (>=2.0)。チャレンジは短命のオンメモリキャッシュで保管する
（単一プロセス・自己ホスト前提。複数ワーカー化する場合は Redis 等に置き換える）。
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import get_settings
from app.core.db import get_db
from app.deps import get_current_user
from app.models.session import Session
from app.models.user import User, WebauthnCredential
from app.schemas.auth import CurrentUser
from app.services import audit

router = APIRouter(prefix="/webauthn", tags=["webauthn"])

# challenge_id → (challenge_b64, user_id, expires_at_epoch)
_CHALLENGES: dict[str, tuple[str, str | None, float]] = {}
_CHALLENGE_TTL = 300  # 5 分


def _save_challenge(challenge: bytes, user_id: str | None) -> str:
    _gc_challenges()
    cid = secrets.token_urlsafe(24)
    _CHALLENGES[cid] = (
        base64.urlsafe_b64encode(challenge).decode().rstrip("="),
        user_id,
        time.time() + _CHALLENGE_TTL,
    )
    return cid


def _pop_challenge(cid: str) -> tuple[bytes, str | None]:
    entry = _CHALLENGES.pop(cid, None)
    if entry is None:
        raise HTTPException(status_code=400, detail="challenge expired or missing")
    challenge_b64, uid, expires = entry
    if expires < time.time():
        raise HTTPException(status_code=400, detail="challenge expired")
    pad = "=" * (-len(challenge_b64) % 4)
    return base64.urlsafe_b64decode(challenge_b64 + pad), uid


def _gc_challenges() -> None:
    now = time.time()
    for cid in [c for c, (_, _, exp) in _CHALLENGES.items() if exp < now]:
        _CHALLENGES.pop(cid, None)


def _set_session_cookie(response: Response, token: str, ttl_days: int) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
        path="/",
    )


# ---------------- Registration（ログイン済みユーザーに紐づける） ----------------


@router.post("/register/begin")
async def register_begin(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    existing = await db.scalars(
        select(WebauthnCredential).where(WebauthnCredential.user_id == user.id)
    )
    exclude = [
        PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing
    ]

    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=str(user.id).encode("utf-8"),
        user_name=user.email,
        user_display_name=user.display_name,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
    )
    cid = _save_challenge(options.challenge, str(user.id))
    return {"challenge_id": cid, "options": json.loads(options_to_json(options))}


@router.post("/register/finish")
async def register_finish(
    request: Request,
    payload: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    cid = payload.get("challenge_id")
    credential = payload.get("credential")
    nickname = payload.get("nickname")
    if not cid or not credential:
        raise HTTPException(status_code=400, detail="challenge_id and credential are required")

    challenge, uid = _pop_challenge(cid)
    if uid != str(user.id):
        raise HTTPException(status_code=400, detail="challenge user mismatch")

    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_origin=settings.webauthn_origins_list,
            expected_rp_id=settings.webauthn_rp_id,
            require_user_verification=False,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"verification failed: {e}")

    cred = WebauthnCredential(
        user_id=user.id,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        nickname=nickname or "passkey",
    )
    db.add(cred)
    await audit.record(
        db,
        user_id=user.id,
        action="passkey.register",
        request=request,
        target_type="user",
        target_id=user.id,
    )
    await db.commit()
    await db.refresh(cred)
    return {"id": str(cred.id), "nickname": cred.nickname}


@router.get("/credentials")
async def list_credentials(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(WebauthnCredential).where(WebauthnCredential.user_id == user.id)
    )
    return [
        {
            "id": str(c.id),
            "nickname": c.nickname,
            "created_at": c.created_at.isoformat(),
            "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
        }
        for c in rows
    ]


@router.delete("/credentials/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    cred_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    cred = await db.get(WebauthnCredential, cred_id)
    if cred is None or cred.user_id != user.id:
        raise HTTPException(status_code=404, detail="credential not found")
    await db.delete(cred)
    await audit.record(
        db,
        user_id=user.id,
        action="passkey.delete",
        request=request,
        target_type="user",
        target_id=user.id,
    )
    await db.commit()


# ---------------- Authentication ----------------


@router.post("/login/begin")
async def login_begin(
    payload: dict = Body(default_factory=dict),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    email = (payload or {}).get("email")
    allow: list[PublicKeyCredentialDescriptor] = []

    if email:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            # ユーザー存在をリークしないよう、空リストで進める（discoverable credentials のフォールバック）
            allow = []
        else:
            creds = await db.scalars(
                select(WebauthnCredential).where(WebauthnCredential.user_id == user.id)
            )
            allow = [PublicKeyCredentialDescriptor(id=c.credential_id) for c in creds]

    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    cid = _save_challenge(options.challenge, None)
    return {"challenge_id": cid, "options": json.loads(options_to_json(options))}


@router.post("/login/finish")
async def login_finish(
    request: Request,
    response: Response,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    settings = get_settings()
    cid = payload.get("challenge_id")
    credential = payload.get("credential")
    if not cid or not credential:
        raise HTTPException(status_code=400, detail="challenge_id and credential are required")

    challenge, _ = _pop_challenge(cid)

    raw_id_b64 = credential.get("rawId") or credential.get("id")
    if not raw_id_b64:
        raise HTTPException(status_code=400, detail="credential id missing")
    pad = "=" * (-len(raw_id_b64) % 4)
    raw_id = base64.urlsafe_b64decode(raw_id_b64 + pad)

    cred_row = await db.scalar(
        select(WebauthnCredential).where(WebauthnCredential.credential_id == raw_id)
    )
    if cred_row is None:
        raise HTTPException(status_code=401, detail="unknown credential")

    user = await db.get(User, cred_row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origins_list,
            credential_public_key=cred_row.public_key,
            credential_current_sign_count=cred_row.sign_count,
            require_user_verification=False,
        )
    except Exception as e:
        await audit.record(
            db,
            user_id=user.id,
            action="login_failed",
            request=request,
            target_type="user",
            target_id=user.id,
            metadata={"reason": "passkey", "error": str(e)},
        )
        await db.commit()
        raise HTTPException(status_code=401, detail=f"verification failed: {e}")

    cred_row.sign_count = verification.new_sign_count
    cred_row.last_used_at = datetime.now(tz=timezone.utc)
    user.last_login_at = datetime.now(tz=timezone.utc)

    from app.core.security import generate_session_token

    token = generate_session_token()
    expires_at = datetime.now(tz=timezone.utc) + timedelta(days=settings.session_ttl_days)
    db.add(
        Session(
            id=token,
            user_id=user.id,
            expires_at=expires_at,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    await audit.record(
        db,
        user_id=user.id,
        action="login",
        request=request,
        target_type="user",
        target_id=user.id,
        metadata={"method": "passkey"},
    )
    await db.commit()

    _set_session_cookie(response, token, settings.session_ttl_days)
    return CurrentUser(
        id=str(user.id), email=user.email, display_name=user.display_name, role=user.role
    )
