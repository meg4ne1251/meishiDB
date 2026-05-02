import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

CARD_STATUSES = ("uploaded", "ocr_running", "ocr_done", "confirmed", "archived")
CARD_SOURCES = ("upload", "camera", "scanner", "manual", "email")


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','ocr_running','ocr_done','confirmed','archived')",
            name="cards_status_check",
        ),
        CheckConstraint(
            "source IN ('upload','camera','scanner','manual','email')",
            name="cards_source_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="uploaded")
    source: Mapped[str] = mapped_column(String, nullable=False, server_default="manual")
    image_front_key: Mapped[str | None] = mapped_column(String)
    image_back_key: Mapped[str | None] = mapped_column(String)

    scanned_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)

    fields: Mapped["CardField"] = relationship(
        back_populates="card", uselist=False, cascade="all, delete-orphan"
    )
    tags: Mapped[list["CardTag"]] = relationship(cascade="all, delete-orphan")
    memos: Mapped[list["CardMemo"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    shares: Mapped[list["CardShare"]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )


class CardField(Base):
    __tablename__ = "card_fields"

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    person_name: Mapped[str | None] = mapped_column(String)
    person_name_kana: Mapped[str | None] = mapped_column(String)
    company: Mapped[str | None] = mapped_column(String)
    department: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    postal_code: Mapped[str | None] = mapped_column(String)
    address: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    mobile: Mapped[str | None] = mapped_column(String)
    fax: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    website: Mapped[str | None] = mapped_column(String)
    raw_ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[dict | None] = mapped_column(JSONB)

    card: Mapped[Card] = relationship(back_populates="fields")


class CardTag(Base):
    __tablename__ = "card_tags"

    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class CardMemo(Base):
    __tablename__ = "card_memos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)

    card: Mapped[Card] = relationship(back_populates="memos")


class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class CardShare(Base):
    __tablename__ = "card_shares"
    __table_args__ = (
        CheckConstraint("permission IN ('view','edit')", name="card_shares_permission_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cards.id", ondelete="CASCADE"), nullable=False
    )
    shared_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    shared_with: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    permission: Mapped[str] = mapped_column(String, nullable=False, server_default="view")
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)

    card: Mapped[Card] = relationship(back_populates="shares")
