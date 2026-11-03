"""auth lookup function

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import make_url

from app.core.config import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    op.execute(
        """
        CREATE FUNCTION auth_find_user(p_phone text, p_email text)
        RETURNS TABLE (id uuid, tenant_id uuid, role text, is_active boolean)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT u.id, u.tenant_id, u.role, u.is_active FROM users u
            WHERE (p_phone IS NOT NULL AND u.phone = p_phone)
               OR (p_email IS NOT NULL AND u.email = p_email)
            LIMIT 1
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION auth_find_user(text, text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_find_user(text, text) TO {role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_find_user(text, text)")
