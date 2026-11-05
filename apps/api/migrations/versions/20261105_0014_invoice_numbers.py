"""invoice number sequence

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import make_url

from app.core.config import get_settings

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    op.execute("CREATE SEQUENCE invoice_no_seq")
    op.execute(f"GRANT USAGE ON SEQUENCE invoice_no_seq TO {role}")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS invoice_no_seq")
