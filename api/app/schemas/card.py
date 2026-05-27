from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CardFieldsBase(BaseModel):
    person_name: str | None = None
    person_name_kana: str | None = None
    company: str | None = None
    department: str | None = None
    title: str | None = None
    postal_code: str | None = None
    address: str | None = None
    phone: str | None = None
    mobile: str | None = None
    fax: str | None = None
    email: str | None = None
    website: str | None = None


class CardFieldsRead(CardFieldsBase):
    model_config = ConfigDict(from_attributes=True)
    latitude: float | None = None
    longitude: float | None = None
    raw_ocr_text: str | None = None
    ocr_confidence: dict | None = None


class TagSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    color: str | None = None


class CardCreate(BaseModel):
    source: str = Field(default="manual")
    fields: CardFieldsBase = Field(default_factory=CardFieldsBase)
    tag_ids: list[UUID] = Field(default_factory=list)


class CardUpdate(BaseModel):
    status: str | None = None
    fields: CardFieldsBase | None = None
    tag_ids: list[UUID] | None = None


class CardSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID
    status: str
    source: str
    image_front_key: str | None = None
    image_back_key: str | None = None
    created_at: datetime
    updated_at: datetime
    fields: CardFieldsRead | None = None
    tags: list[TagSummary] = Field(default_factory=list)
    is_favorite: bool = False
    shared: bool = False


class CardListResponse(BaseModel):
    items: list[CardSummary]
    total: int


class CardDetail(CardSummary):
    pass


class CardGeoPoint(BaseModel):
    id: UUID
    person_name: str | None = None
    company: str | None = None
    address: str | None = None
    latitude: float
    longitude: float
    shared: bool = False


class CardGeoResponse(BaseModel):
    items: list[CardGeoPoint]


class ShareRequest(BaseModel):
    user_email: str
    permission: str = Field(default="view", pattern="^(view|edit)$")


class ShareInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    card_id: UUID
    shared_by: UUID
    shared_with: UUID
    permission: str
    created_at: datetime
