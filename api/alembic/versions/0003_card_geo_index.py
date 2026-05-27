"""add partial index for geocoded card_fields

Revision ID: 0003_card_geo_index
Revises: 0002_card_geo
Create Date: 2026-05-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_card_geo_index"
down_revision: str | None = "0002_card_geo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # /cards/geo は座標を持つ行だけを引くので、部分インデックスにして小さく保つ。
    op.create_index(
        "ix_card_fields_lat_lng",
        "card_fields",
        ["latitude", "longitude"],
        postgresql_where=sa.text("latitude IS NOT NULL AND longitude IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_card_fields_lat_lng", table_name="card_fields")
