"""assignee, customer tags, lead cancel reason, reminder and note

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CANCEL_REASONS = "('price', 'no_stock', 'no_answer', 'changed_mind', 'duplicate', 'other')"


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    for table in ("conversations", "leads"):
        op.add_column(table, sa.Column("assignee_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_assignee_id_users"),
            table,
            "users",
            ["assignee_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(op.f(f"ix_{table}_assignee_id"), table, ["assignee_id"], unique=False)
    op.add_column("leads", sa.Column("cancel_reason", sa.String(length=16), nullable=True))
    op.add_column("leads", sa.Column("remind_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("note", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_leads_cancel_reason"), "leads", f"cancel_reason IN {CANCEL_REASONS}"
    )
    op.create_index(
        "ix_leads_remind_at",
        "leads",
        ["remind_at"],
        unique=False,
        postgresql_where=sa.text("remind_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_leads_remind_at", table_name="leads")
    op.drop_constraint(op.f("ck_leads_cancel_reason"), "leads", type_="check")
    op.drop_column("leads", "note")
    op.drop_column("leads", "remind_at")
    op.drop_column("leads", "cancel_reason")
    for table in ("leads", "conversations"):
        op.drop_index(op.f(f"ix_{table}_assignee_id"), table_name=table)
        op.drop_constraint(op.f(f"fk_{table}_assignee_id_users"), table, type_="foreignkey")
        op.drop_column(table, "assignee_id")
    op.drop_column("customers", "tags")
