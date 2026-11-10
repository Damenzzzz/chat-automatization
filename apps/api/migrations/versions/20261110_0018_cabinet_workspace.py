"""bot pause, reply templates and customer notes

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("bot_paused", sa.Boolean(), server_default=sa.text("false")))
    op.execute("UPDATE tenants SET bot_paused = false WHERE bot_paused IS NULL")
    op.alter_column("tenants", "bot_paused", nullable=False)
    op.add_column(
        "tenants",
        sa.Column(
            "reply_templates",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("customers", sa.Column("note", sa.Text()))


def downgrade() -> None:
    op.drop_column("customers", "note")
    op.drop_column("tenants", "reply_templates")
    op.drop_column("tenants", "bot_paused")
