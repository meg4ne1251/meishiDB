"""監査ログ append-only 記録。

`docs/architecture.md` の「監査対象アクション」一覧に対応。
"""

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record(
    db: AsyncSession,
    *,
    user_id: UUID | None,
    action: str,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: str | UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    ip = None
    user_agent = None
    if request is not None:
        ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=ip,
            user_agent=user_agent,
            audit_metadata=metadata,
        )
    )
    # commit はルーター側でまとめて行う（呼び出し元のトランザクションに乗る）
