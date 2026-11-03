"""product name hash for rows without sku

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("name_hash", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_products_tenant_id_name_hash",
        "products",
        ["tenant_id", "name_hash"],
        unique=True,
        postgresql_where=sa.text("sku_norm IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_products_tenant_id_name_hash", table_name="products")
    op.drop_column("products", "name_hash")
