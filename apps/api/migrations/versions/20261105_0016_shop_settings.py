"""shop links and onboarding progress

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "links", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    op.add_column(
        "tenants", sa.Column("onboarding_step", sa.Integer(), server_default="1", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("tenants", "onboarding_step")
    op.drop_column("tenants", "links")
