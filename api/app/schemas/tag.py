from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: str | None = Field(default=None, max_length=20)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    color: str | None = Field(default=None, max_length=20)


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    color: str | None = None
    created_at: datetime
