"""langgraph checkpoints in agent_state schema

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import make_url

from app.agent.checkpoint import SCHEMA, setup_checkpointer
from app.core.config import get_settings

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    settings = get_settings()
    app_role = make_url(settings.database_url).username or ""
    with op.get_context().autocommit_block():
        setup_checkpointer(settings.database_owner_url, app_role)


def downgrade() -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
