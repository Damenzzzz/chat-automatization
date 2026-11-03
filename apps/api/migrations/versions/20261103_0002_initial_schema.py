"""initial schema

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("tenants", "users", "bot_profiles", "channels")


def upgrade() -> None:
    _create_tables()
    _create_updated_at_triggers()


def downgrade() -> None:
    _drop_tables()
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")


def _create_updated_at_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END $$
        """
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def _create_tables() -> None:
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("niche", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("plan", sa.String(length=32), server_default="trial", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="onboarding", nullable=False),
        sa.Column("balance_kzt", sa.BigInteger(), server_default="0", nullable=False),
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
        sa.CheckConstraint(
            "status IN ('onboarding', 'active', 'suspended')", name=op.f("ck_tenants_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
    )
    op.create_table(
        "bot_profiles",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tone", sa.Text(), nullable=True),
        sa.Column(
            "rules",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("greeting", sa.Text(), nullable=True),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.String(length=8)),
            server_default=sa.text("'{ru,kk}'"),
            nullable=False,
        ),
        sa.Column(
            "model_policy",
            postgresql.JSONB(astext_type=sa.Text()),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_bot_profiles_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_profiles")),
        sa.UniqueConstraint("tenant_id", "version", name=op.f("uq_bot_profiles_tenant_id")),
    )
    op.create_index(op.f("ix_bot_profiles_tenant_id"), "bot_profiles", ["tenant_id"], unique=False)
    op.create_table(
        "channels",
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("credentials_enc", sa.LargeBinary(), nullable=True),
        sa.Column("webhook_secret", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'error', 'disabled')", name=op.f("ck_channels_status")
        ),
        sa.CheckConstraint(
            "type IN ('whatsapp', 'instagram', 'telegram', 'web')", name=op.f("ck_channels_type")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_channels_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channels")),
    )
    op.create_index(op.f("ix_channels_tenant_id"), "channels", ["tenant_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'manager', 'admin')", name=op.f("ck_users_role")),
        sa.CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name=op.f("ck_users_contact")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_users_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)
    op.create_index("uq_users_email", "users", ["email"], unique=True)
    op.create_index("uq_users_phone", "users", ["phone"], unique=True)


def _drop_tables() -> None:
    op.drop_index("uq_users_phone", table_name="users")
    op.drop_index("uq_users_email", table_name="users")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_channels_tenant_id"), table_name="channels")
    op.drop_table("channels")
    op.drop_index(op.f("ix_bot_profiles_tenant_id"), table_name="bot_profiles")
    op.drop_table("bot_profiles")
    op.drop_table("tenants")
