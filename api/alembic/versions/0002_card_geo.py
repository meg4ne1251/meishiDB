"""add geocoding columns to card_fields

Revision ID: 0002_card_geo
Revises: 0001_init
Create Date: 2026-05-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_card_geo"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("card_fields", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("card_fields", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column(
        "card_fields",
        sa.Column("geocoded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("card_fields", "geocoded_at")
    op.drop_column("card_fields", "longitude")
    op.drop_column("card_fields", "latitude")
