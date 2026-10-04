from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.text import DatabaseText


class TagCreate(BaseModel):
    name: DatabaseText = Field(min_length=1, max_length=50)
    color: DatabaseText | None = Field(default=None, max_length=20)


class TagUpdate(BaseModel):
    name: DatabaseText | None = Field(default=None, min_length=1, max_length=50)
    color: DatabaseText | None = Field(default=None, max_length=20)


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    color: str | None = None
    created_at: datetime
