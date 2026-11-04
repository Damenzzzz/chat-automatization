"""bot profile versions: single active version, origin and author

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bot_profiles", sa.Column("based_on", sa.Integer(), nullable=True))
    op.add_column(
        "bot_profiles",
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_bot_profiles_created_by_users"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_bot_profiles_tenant_id_active",
        "bot_profiles",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_bot_profiles_tenant_id_active", table_name="bot_profiles")
    op.drop_column("bot_profiles", "created_by")
    op.drop_column("bot_profiles", "based_on")
