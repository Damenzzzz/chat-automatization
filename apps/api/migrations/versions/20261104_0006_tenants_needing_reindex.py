"""tenants needing embedding reindex

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import make_url

from app.core.config import get_settings

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    op.execute(
        """
        CREATE FUNCTION tenants_needing_reindex() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT tenant_id FROM products WHERE embedding_stale OR embedding IS NULL
            UNION
            SELECT tenant_id FROM kb_chunks WHERE embedding_stale OR embedding IS NULL
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION tenants_needing_reindex() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION tenants_needing_reindex() TO {role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS tenants_needing_reindex()")
