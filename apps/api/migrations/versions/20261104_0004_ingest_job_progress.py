"""ingest job progress and pending status

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingest_jobs", sa.Column("file_name", sa.String(length=255), nullable=True))
    op.add_column("ingest_jobs", sa.Column("file_type", sa.String(length=8), nullable=True))
    op.add_column("ingest_jobs", sa.Column("rows_total", sa.Integer(), nullable=True))
    op.add_column(
        "ingest_jobs", sa.Column("rows_done", sa.Integer(), server_default="0", nullable=False)
    )
    op.drop_constraint(op.f("ck_ingest_jobs_status"), "ingest_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_ingest_jobs_status"),
        "ingest_jobs",
        "status IN ('pending', 'queued', 'running', 'done', 'failed')",
    )
    op.create_check_constraint(
        op.f("ck_ingest_jobs_file_type"), "ingest_jobs", "file_type IN ('xlsx', 'csv')"
    )
    op.alter_column("ingest_jobs", "status", server_default="pending")


def downgrade() -> None:
    op.alter_column("ingest_jobs", "status", server_default="queued")
    op.drop_constraint(op.f("ck_ingest_jobs_file_type"), "ingest_jobs", type_="check")
    op.drop_constraint(op.f("ck_ingest_jobs_status"), "ingest_jobs", type_="check")
    op.execute("UPDATE ingest_jobs SET status = 'queued' WHERE status = 'pending'")
    op.create_check_constraint(
        op.f("ck_ingest_jobs_status"),
        "ingest_jobs",
        "status IN ('queued', 'running', 'done', 'failed')",
    )
    op.drop_column("ingest_jobs", "rows_done")
    op.drop_column("ingest_jobs", "rows_total")
    op.drop_column("ingest_jobs", "file_type")
    op.drop_column("ingest_jobs", "file_name")
