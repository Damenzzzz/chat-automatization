"""idle dialogs, search log retention and stale leads

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import make_url

from app.core.config import get_settings

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTIONS = {
    "retire_idle_conversations(integer, integer)": """
        CREATE FUNCTION retire_idle_conversations(idle_days integer, sandbox_days integer)
        RETURNS SETOF uuid
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
            WITH closed AS (
                UPDATE conversations SET status = 'closed'
                WHERE status = 'open' AND NOT sandbox
                  AND last_message_at < now() - make_interval(days => idle_days)
                RETURNING id
            ), removed AS (
                DELETE FROM conversations
                WHERE sandbox
                  AND coalesce(last_message_at, created_at)
                      < now() - make_interval(days => sandbox_days)
                RETURNING id
            )
            SELECT id FROM closed UNION ALL SELECT id FROM removed
        $$
    """,
    "purge_search_log(integer)": """
        CREATE FUNCTION purge_search_log(keep_days integer) RETURNS integer
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
            WITH removed AS (
                DELETE FROM search_log
                WHERE created_at < now() - make_interval(days => keep_days)
                RETURNING 1
            )
            SELECT count(*)::integer FROM removed
        $$
    """,
    "stale_new_leads(integer)": """
        CREATE FUNCTION stale_new_leads(wait_hours integer)
        RETURNS TABLE (tenant_id uuid, lead_id uuid, total_kzt bigint)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT l.tenant_id, l.id, l.total_kzt FROM leads l
            WHERE l.status = 'new'
              AND l.created_at < now() - make_interval(hours => wait_hours)
              AND l.created_at > now() - interval '3 days'
        $$
    """,
}


def upgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    for signature, body in FUNCTIONS.items():
        op.execute(body)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")


def downgrade() -> None:
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
