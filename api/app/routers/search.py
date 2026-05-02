"""管理用：Meilisearch 全件再構築エンドポイント。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.deps import get_current_admin
from app.models.user import User
from app.services import search_index

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/reindex")
async def reindex(
    _: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int | bool]:
    if not search_index._is_configured():
        return {"configured": False, "indexed": 0}
    count = await search_index.reindex_all(db)
    return {"configured": True, "indexed": count}
