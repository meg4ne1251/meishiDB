"""init schema

Revision ID: 0001_init
Revises:
Create Date: 2026-04-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin','member')", name="users_role_check"),
    )

    op.create_table(
        "webauthn_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("transports", postgresql.ARRAY(sa.String())),
        sa.Column("nickname", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="uploaded"),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("image_front_key", sa.String(), nullable=True),
        sa.Column("image_back_key", sa.String(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('uploaded','ocr_running','ocr_done','confirmed','archived')",
            name="cards_status_check",
        ),
        sa.CheckConstraint(
            "source IN ('upload','camera','scanner','manual','email')",
            name="cards_source_check",
        ),
    )
    op.create_index("idx_cards_owner", "cards", ["owner_id"])
    op.create_index("idx_cards_updated", "cards", ["updated_at"])

    op.create_table(
        "card_fields",
        sa.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("person_name", sa.String()),
        sa.Column("person_name_kana", sa.String()),
        sa.Column("company", sa.String()),
        sa.Column("department", sa.String()),
        sa.Column("title", sa.String()),
        sa.Column("postal_code", sa.String()),
        sa.Column("address", sa.String()),
        sa.Column("phone", sa.String()),
        sa.Column("mobile", sa.String()),
        sa.Column("fax", sa.String()),
        sa.Column("email", sa.String()),
        sa.Column("website", sa.String()),
        sa.Column("raw_ocr_text", sa.Text()),
        sa.Column("ocr_confidence", postgresql.JSONB()),
    )

    op.create_table(
        "tags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="tags_owner_name_unique"),
    )

    op.create_table(
        "card_tags",
        sa.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "card_memos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "favorites",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "card_shares",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "card_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shared_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shared_with",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("permission", sa.String(), nullable=False, server_default="view"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("permission IN ('view','edit')", name="card_shares_permission_check"),
        sa.UniqueConstraint("card_id", "shared_with", name="card_shares_card_user_unique"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String()),
        sa.Column("target_id", sa.String()),
        sa.Column("ip", postgresql.INET()),
        sa.Column("user_agent", sa.String()),
        sa.Column("metadata", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_audit_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index("idx_audit_target", "audit_logs", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("card_shares")
    op.drop_table("favorites")
    op.drop_table("card_memos")
    op.drop_table("card_tags")
    op.drop_table("tags")
    op.drop_table("card_fields")
    op.drop_table("cards")
    op.drop_table("sessions")
    op.drop_table("webauthn_credentials")
    op.drop_table("users")
