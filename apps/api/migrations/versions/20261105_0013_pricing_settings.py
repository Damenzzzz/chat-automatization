"""pricing settings, effective pricing lookup; balance comes only from ledger

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import make_url
from sqlalchemy.dialects import postgresql

from app.core.config import get_settings

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SATUSHY_TENANT_ID = "5a705e00-0000-4000-8000-000000000001"
CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    role = f'"{make_url(get_settings().database_url).username}"'
    op.create_table(
        "pricing_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("markup", sa.Numeric(6, 3), server_default="3", nullable=False),
        sa.Column("kzt_per_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "model_prices",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.CheckConstraint("markup >= 3", name=op.f("ck_pricing_settings_markup")),
        sa.CheckConstraint("kzt_per_usd > 0", name=op.f("ck_pricing_settings_kzt_per_usd")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_pricing_settings_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_settings")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_pricing_settings_tenant_id")),
    )
    op.create_index(
        op.f("ix_pricing_settings_tenant_id"), "pricing_settings", ["tenant_id"], unique=False
    )
    op.execute(
        "CREATE TRIGGER set_updated_at BEFORE UPDATE ON pricing_settings "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute("ALTER TABLE pricing_settings ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON pricing_settings "
        f"USING (tenant_id = {CURRENT_TENANT}) WITH CHECK (tenant_id = {CURRENT_TENANT})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON pricing_settings TO {role}")
    op.execute(
        f"""
        CREATE FUNCTION pricing_effective()
        RETURNS TABLE (markup numeric, kzt_per_usd numeric, model_prices jsonb)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT p.markup, p.kzt_per_usd, p.model_prices FROM pricing_settings p
            WHERE p.tenant_id IN ({CURRENT_TENANT}, '{SATUSHY_TENANT_ID}'::uuid)
            ORDER BY p.tenant_id = {CURRENT_TENANT} DESC
            LIMIT 1
        $$
        """  # noqa: S608
    )
    op.execute("REVOKE ALL ON FUNCTION pricing_effective() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION pricing_effective() TO {role}")
    op.drop_column("tenants", "balance_kzt")


def downgrade() -> None:
    op.add_column(
        "tenants", sa.Column("balance_kzt", sa.BigInteger(), server_default="0", nullable=False)
    )
    op.execute("DROP FUNCTION IF EXISTS pricing_effective()")
    op.drop_table("pricing_settings")
