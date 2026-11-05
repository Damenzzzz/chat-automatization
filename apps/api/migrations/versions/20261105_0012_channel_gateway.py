"""channel gateway: widget key, domain, lookups, single open conversation

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import make_url

from app.core.config import get_settings

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = """id uuid, tenant_id uuid, type text, status text, webhook_secret text,
             domain text, credentials_enc bytea"""
SELECT = """SELECT c.id, c.tenant_id, c.type::text, c.status::text, c.webhook_secret::text,
                   c.domain::text, c.credentials_enc FROM channels c"""


def upgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    op.add_column("channels", sa.Column("public_key", sa.String(64), nullable=True))
    op.add_column("channels", sa.Column("domain", sa.String(253), nullable=True))
    op.create_index("uq_channels_public_key", "channels", ["public_key"], unique=True)
    op.create_index(
        "uq_channels_type_external_id", "channels", ["type", "external_id"], unique=True
    )
    op.create_index(
        "uq_conversations_open",
        "conversations",
        ["tenant_id", "customer_id", "channel_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open' AND NOT sandbox"),
    )
    for name, arg, where in (
        ("channel_lookup", "uuid", "c.id = p"),
        ("channel_by_public_key", "text", "c.public_key = p"),
    ):
        op.execute(
            f"""
            CREATE FUNCTION {name}(p {arg}) RETURNS TABLE ({COLUMNS})
            LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
                {SELECT} WHERE {where}
            $$
            """
        )
        op.execute(f"REVOKE ALL ON FUNCTION {name}({arg}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {name}({arg}) TO {role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS channel_by_public_key(text)")
    op.execute("DROP FUNCTION IF EXISTS channel_lookup(uuid)")
    op.drop_index("uq_conversations_open", table_name="conversations")
    op.drop_index("uq_channels_type_external_id", table_name="channels")
    op.drop_index("uq_channels_public_key", table_name="channels")
    op.drop_column("channels", "domain")
    op.drop_column("channels", "public_key")
