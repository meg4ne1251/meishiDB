import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="tags_owner_name_unique"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
