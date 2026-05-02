from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.deps import get_current_user
from app.models.tag import Tag
from app.models.user import User
from app.schemas.tag import TagCreate, TagRead, TagUpdate

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=list[TagRead])
async def list_tags(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[TagRead]:
    rows = await db.scalars(
        select(Tag).where(Tag.owner_id == user.id).order_by(Tag.name)
    )
    return [TagRead.model_validate(t) for t in rows]


@router.post("", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(
    payload: TagCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TagRead:
    tag = Tag(owner_id=user.id, name=payload.name, color=payload.color)
    db.add(tag)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="tag name already exists")
    await db.refresh(tag)
    return TagRead.model_validate(tag)


@router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: UUID,
    payload: TagUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TagRead:
    tag = await db.get(Tag, tag_id)
    if tag is None or tag.owner_id != user.id:
        raise HTTPException(status_code=404, detail="tag not found")
    if payload.name is not None:
        tag.name = payload.name
    if payload.color is not None:
        tag.color = payload.color
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="tag name already exists")
    await db.refresh(tag)
    return TagRead.model_validate(tag)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    tag = await db.get(Tag, tag_id)
    if tag is None or tag.owner_id != user.id:
        raise HTTPException(status_code=404, detail="tag not found")
    await db.delete(tag)
    await db.commit()
