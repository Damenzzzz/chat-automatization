"""message usage, cost and trace; sandbox conversations

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("cached_tokens", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True))
    op.add_column("messages", sa.Column("trace", postgresql.JSONB(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("sandbox", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("conversations", "sandbox")
    op.drop_column("messages", "trace")
    op.drop_column("messages", "cost_usd")
    op.drop_column("messages", "cached_tokens")
