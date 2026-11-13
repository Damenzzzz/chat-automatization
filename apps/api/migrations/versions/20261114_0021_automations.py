"""automations, their run history and follow-up queue

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-14
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import make_url
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"
KINDS = "('digest', 'stock', 'followup', 'lead_reminders')"
EMPTY_JSON = sa.text("'{}'::jsonb")

FUNCTIONS = {
    "due_automations()": """
        CREATE FUNCTION due_automations() RETURNS TABLE (tenant_id uuid, kind text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT a.tenant_id, a.kind::text FROM automations a
            JOIN tenants t ON t.id = a.tenant_id
            WHERE a.enabled AND t.status <> 'suspended'
            UNION
            SELECT l.tenant_id, 'lead_reminders' FROM leads l
            JOIN tenants t ON t.id = l.tenant_id
            WHERE t.status <> 'suspended'
              AND l.status IN ('new', 'in_progress')
              AND (
                  l.remind_at <= now()
                  OR (l.status = 'new' AND l.created_at > now() - interval '3 days')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM automations a
                  WHERE a.tenant_id = l.tenant_id AND a.kind = 'lead_reminders'
              )
        $$
    """,
    "purge_automation_runs(integer)": """
        CREATE FUNCTION purge_automation_runs(keep_days integer) RETURNS integer
        LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
            WITH runs AS (
                DELETE FROM automation_runs
                WHERE created_at < now() - make_interval(days => keep_days)
                RETURNING 1
            ), queue AS (
                DELETE FROM followups
                WHERE status <> 'pending'
                  AND created_at < now() - make_interval(days => keep_days)
                RETURNING 1
            )
            SELECT ((SELECT count(*) FROM runs) + (SELECT count(*) FROM queue))::integer
        $$
    """,
}

STALE_NEW_LEADS = """
    CREATE FUNCTION stale_new_leads(wait_hours integer)
    RETURNS TABLE (tenant_id uuid, lead_id uuid, total_kzt bigint)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
        SELECT l.tenant_id, l.id, l.total_kzt FROM leads l
        WHERE l.status = 'new'
          AND l.created_at < now() - make_interval(hours => wait_hours)
          AND l.created_at > now() - interval '3 days'
    $$
"""


def base_columns(table: str) -> list[sa.Column[Any] | sa.Constraint]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{table}_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def protect(table: str, role: str) -> None:
    op.create_index(op.f(f"ix_{table}_tenant_id"), table, ["tenant_id"], unique=False)
    op.execute(
        f"CREATE TRIGGER set_updated_at BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING (tenant_id = {CURRENT_TENANT}) WITH CHECK (tenant_id = {CURRENT_TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {role}")


def upgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    op.create_table(
        "automations",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("settings", postgresql.JSONB(), server_default=EMPTY_JSON, nullable=False),
        sa.Column("state", postgresql.JSONB(), server_default=EMPTY_JSON, nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        *base_columns("automations"),
        sa.CheckConstraint(f"kind IN {KINDS}", name=op.f("ck_automations_kind")),
        sa.UniqueConstraint("tenant_id", "kind", name=op.f("uq_automations_tenant_id_kind")),
    )
    protect("automations", role)

    op.create_table(
        "automation_runs",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(), server_default=EMPTY_JSON, nullable=False),
        *base_columns("automation_runs"),
        sa.CheckConstraint(f"kind IN {KINDS}", name=op.f("ck_automation_runs_kind")),
        sa.CheckConstraint(
            "trigger IN ('schedule', 'manual')", name=op.f("ck_automation_runs_trigger")
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'empty', 'failed')", name=op.f("ck_automation_runs_status")
        ),
    )
    protect("automation_runs", role)
    op.create_index(
        "ix_automation_runs_tenant_id_kind_created_at",
        "automation_runs",
        ["tenant_id", "kind", "created_at"],
        unique=False,
    )

    op.create_table(
        "followups",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *base_columns("followups"),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'rejected', 'expired', 'failed')",
            name=op.f("ck_followups_status"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_followups_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_followups_decided_by_users"),
            ondelete="SET NULL",
        ),
    )
    protect("followups", role)
    op.create_index(
        op.f("ix_followups_conversation_id"), "followups", ["conversation_id"], unique=False
    )
    op.create_index(
        "ix_followups_tenant_id_status_created_at",
        "followups",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )

    op.execute("DROP FUNCTION IF EXISTS stale_new_leads(integer)")
    for signature, body in FUNCTIONS.items():
        op.execute(body)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {role}")


def downgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {signature}")
    op.execute(STALE_NEW_LEADS)
    op.execute("REVOKE ALL ON FUNCTION stale_new_leads(integer) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION stale_new_leads(integer) TO {role}")
    op.drop_table("followups")
    op.drop_table("automation_runs")
    op.drop_table("automations")
