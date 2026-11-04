"""search log kind, result count and stock flag

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "search_log",
        sa.Column("kind", sa.String(length=16), server_default="product", nullable=False),
    )
    op.add_column(
        "search_log",
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("search_log", sa.Column("has_in_stock", sa.Boolean(), nullable=True))
    op.create_check_constraint(
        op.f("ck_search_log_kind"), "search_log", "kind IN ('product', 'kb')"
    )
    op.create_index(
        op.f("ix_search_log_tenant_id_created_at"), "search_log", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_search_log_tenant_id_created_at"), table_name="search_log")
    op.drop_constraint(op.f("ck_search_log_kind"), "search_log", type_="check")
    op.drop_column("search_log", "has_in_stock")
    op.drop_column("search_log", "result_count")
    op.drop_column("search_log", "kind")
