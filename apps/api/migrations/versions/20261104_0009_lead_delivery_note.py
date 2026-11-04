"""lead delivery note and comment

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("delivery_note", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "comment")
    op.drop_column("leads", "delivery_note")
