"""notifications, owner telegram chat, paused conversations

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import make_url
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    op.create_table(
        "notifications",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
            name=op.f("fk_notifications_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        op.f("ix_notifications_tenant_id"), "notifications", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_notifications_tenant_id_created_at",
        "notifications",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.execute(
        "CREATE TRIGGER set_updated_at BEFORE UPDATE ON notifications "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON notifications "
        f"USING (tenant_id = {CURRENT_TENANT}) WITH CHECK (tenant_id = {CURRENT_TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON notifications TO {role}")
    op.add_column("users", sa.Column("telegram_chat_id", sa.String(length=32), nullable=True))
    op.add_column("conversations", sa.Column("paused_reason", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        op.f("ck_conversations_paused_reason"),
        "conversations",
        "paused_reason IN ('no_balance', 'rate_limit')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_conversations_paused_reason"), "conversations")
    op.drop_column("conversations", "paused_reason")
    op.drop_column("users", "telegram_chat_id")
    op.drop_table("notifications")
