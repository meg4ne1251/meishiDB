from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import generate_session_token, hash_password, verify_password
from app.deps import get_current_user
from app.models.session import Session
from app.models.user import User
from app.schemas.auth import CurrentUser, LoginRequest, RegisterRequest
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


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


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """初回登録。最初のユーザーは admin、以降は member。

    本来は招待制（管理者の招待リンク）だが、MVP の足場として open registration を許容。
    後で招待制に切り替える際は `INVITE_CODE` チェックを差し込む想定。
    """
    settings = get_settings()

    # 初回 admin 競合を防ぐためアドバイザリロックでシリアライズする。
    # ロックはトランザクション終了時に自動解放される。
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('register_first_user'))"))
    # Check inside the lock: a concurrent registration may have committed while waiting.
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=400, detail="email already registered")
    user_count = await db.scalar(select(User.id).limit(1))
    role = "member" if user_count is not None else "admin"

    user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=await run_in_threadpool(hash_password, payload.password),
        role=role,
    )
    db.add(user)
    await db.flush()

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
        metadata={"reason": "register"},
    )
    await db.commit()

    _set_session_cookie(response, token, settings.session_ttl_days)
    return CurrentUser(
        id=str(user.id), email=user.email, display_name=user.display_name, role=user.role
    )


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    settings = get_settings()
    user = await db.scalar(select(User).where(User.email == payload.email))
    if (
        user is None
        or not user.password_hash
        or not await run_in_threadpool(verify_password, payload.password, user.password_hash)
    ):
        await audit.record(
            db,
            user_id=user.id if user else None,
            action="login_failed",
            request=request,
            target_type="user",
            target_id=user.id if user else None,
            metadata={"email": payload.email},
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="invalid credentials")

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

    user.last_login_at = datetime.now(tz=timezone.utc)

    await audit.record(
        db, user_id=user.id, action="login", request=request, target_type="user", target_id=user.id
    )
    await db.commit()

    _set_session_cookie(response, token, settings.session_ttl_days)
    return CurrentUser(
        id=str(user.id), email=user.email, display_name=user.display_name, role=user.role
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        sess = await db.get(Session, token)
        if sess is not None:
            await audit.record(
                db,
                user_id=sess.user_id,
                action="logout",
                request=request,
                target_type="user",
                target_id=sess.user_id,
            )
            await db.delete(sess)
            await db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> CurrentUser:
    return CurrentUser(
        id=str(user.id), email=user.email, display_name=user.display_name, role=user.role
    )
