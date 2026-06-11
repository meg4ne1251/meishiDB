from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserSummary

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search", response_model=list[UserSummary])
async def search_users(
    q: str = Query(min_length=2, max_length=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserSummary]:
    """共有先選択用。display_name もしくは email の前方一致で 10 件まで返す。"""
    like = f"%{q}%"
    rows = await db.scalars(
        select(User)
        .where(User.id != user.id, (User.display_name.ilike(like)) | (User.email.ilike(like)))
        .order_by(User.display_name)
        .limit(10)
    )
    return [UserSummary.model_validate(u) for u in rows]
