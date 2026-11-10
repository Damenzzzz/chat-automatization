"""tenant-time indexes and idle conversation release

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import make_url

from app.core.config import get_settings

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_messages_tenant_id_created_at", "messages", ["tenant_id", "created_at"]),
    ("ix_leads_tenant_id_created_at", "leads", ["tenant_id", "created_at"]),
    ("ix_leads_tenant_id_updated_at", "leads", ["tenant_id", "updated_at"]),
    ("ix_conversations_tenant_id_updated_at", "conversations", ["tenant_id", "updated_at"]),
    ("ix_ledger_tenant_id_type_created_at", "ledger", ["tenant_id", "type", "created_at"]),
)
STALE = "embedding_stale OR embedding IS NULL"


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)
    for table in ("products", "kb_chunks"):
        op.create_index(f"ix_{table}_stale", table, ["tenant_id"], postgresql_where=sa.text(STALE))
    role = f'"{make_url(get_settings().database_url).username}"'
    op.execute(
        """
        CREATE FUNCTION release_idle_conversations(idle_hours integer) RETURNS integer
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
            WITH released AS (
                UPDATE conversations
                SET mode = 'bot', paused_reason = NULL
                WHERE mode = 'human'
                  AND (
                    (paused_reason IS NULL
                     AND last_message_at < now() - make_interval(hours => idle_hours))
                    OR (paused_reason = 'rate_limit'
                        AND last_message_at < now() - interval '1 hour')
                  )
                RETURNING 1
            )
            SELECT count(*)::integer FROM released
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION release_idle_conversations(integer) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION release_idle_conversations(integer) TO {role}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS release_idle_conversations(integer)")
    for table in ("products", "kb_chunks"):
        op.drop_index(f"ix_{table}_stale", table_name=table)
    for name, table, _ in INDEXES:
        op.drop_index(name, table_name=table)
