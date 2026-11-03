"""initial schema

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "tenants",
    "users",
    "bot_profiles",
    "channels",
    "catalog_sources",
    "ingest_jobs",
    "products",
    "kb_chunks",
)


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
        sa.UniqueConstraint("tenant_id", "version", name=op.f("uq_bot_profiles_tenant_id_version")),
    )
    op.create_index(op.f("ix_bot_profiles_tenant_id"), "bot_profiles", ["tenant_id"], unique=False)
    op.create_table(
        "catalog_sources",
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "column_map",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("schedule", sa.String(length=64), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
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
            "type IN ('excel', 'csv', 'gsheet', 'moysklad', 'onec', 'kaspi')",
            name=op.f("ck_catalog_sources_type"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_catalog_sources_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_sources")),
    )
    op.create_index(
        op.f("ix_catalog_sources_tenant_id"), "catalog_sources", ["tenant_id"], unique=False
    )
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
        "kb_chunks",
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_stale", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('russian', coalesce(title, '') || ' ' || text)", persisted=True
            ),
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
            name=op.f("fk_kb_chunks_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_chunks")),
    )
    op.create_index(
        "ix_kb_chunks_embedding",
        "kb_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(op.f("ix_kb_chunks_tenant_id"), "kb_chunks", ["tenant_id"], unique=False)
    op.create_index("ix_kb_chunks_tsv", "kb_chunks", ["tsv"], unique=False, postgresql_using="gin")
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
    op.create_table(
        "ingest_jobs",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("file_key", sa.String(length=500), nullable=True),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "errors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_ingest_jobs_status")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["catalog_sources.id"],
            name=op.f("fk_ingest_jobs_source_id_catalog_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_ingest_jobs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingest_jobs")),
    )
    op.create_index(op.f("ix_ingest_jobs_source_id"), "ingest_jobs", ["source_id"], unique=False)
    op.create_index(op.f("ix_ingest_jobs_tenant_id"), "ingest_jobs", ["tenant_id"], unique=False)
    op.create_table(
        "products",
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("sku", sa.String(length=100), nullable=True),
        sa.Column(
            "sku_norm",
            sa.String(length=100),
            sa.Computed("upper(regexp_replace(sku, '[\\s-]+', '', 'g'))", persisted=True),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=200), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("synonyms", sa.Text(), nullable=True),
        sa.Column("price", sa.BigInteger(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column(
            "images", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_stale", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('russian', coalesce(name, '')), 'A') || setweight(to_tsvector('russian', coalesce(description, '')), 'B') || setweight(to_tsvector('simple', coalesce(synonyms, '')), 'A')",
                persisted=True,
            ),
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
        sa.CheckConstraint("price >= 0", name=op.f("ck_products_price")),
        sa.CheckConstraint("stock >= 0", name=op.f("ck_products_stock")),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["catalog_sources.id"],
            name=op.f("fk_products_source_id_catalog_sources"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_products_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("tenant_id", "sku_norm", name=op.f("uq_products_tenant_id_sku_norm")),
    )
    op.create_index(
        "ix_products_embedding",
        "products",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_products_name_trgm",
        "products",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_products_sku_norm_trgm",
        "products",
        ["sku_norm"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"sku_norm": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_products_source_id"), "products", ["source_id"], unique=False)
    op.create_index(op.f("ix_products_tenant_id"), "products", ["tenant_id"], unique=False)
    op.create_index("ix_products_tenant_id_price", "products", ["tenant_id", "price"], unique=False)
    op.create_index("ix_products_tenant_id_stock", "products", ["tenant_id", "stock"], unique=False)
    op.create_index("ix_products_tsv", "products", ["tsv"], unique=False, postgresql_using="gin")


def _drop_tables() -> None:
    op.drop_index("ix_products_tsv", table_name="products", postgresql_using="gin")
    op.drop_index("ix_products_tenant_id_stock", table_name="products")
    op.drop_index("ix_products_tenant_id_price", table_name="products")
    op.drop_index(op.f("ix_products_tenant_id"), table_name="products")
    op.drop_index(op.f("ix_products_source_id"), table_name="products")
    op.drop_index(
        "ix_products_sku_norm_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"sku_norm": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_products_name_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index(
        "ix_products_embedding",
        table_name="products",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("products")
    op.drop_index(op.f("ix_ingest_jobs_tenant_id"), table_name="ingest_jobs")
    op.drop_index(op.f("ix_ingest_jobs_source_id"), table_name="ingest_jobs")
    op.drop_table("ingest_jobs")
    op.drop_index("uq_users_phone", table_name="users")
    op.drop_index("uq_users_email", table_name="users")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_table("users")
    op.drop_index("ix_kb_chunks_tsv", table_name="kb_chunks", postgresql_using="gin")
    op.drop_index(op.f("ix_kb_chunks_tenant_id"), table_name="kb_chunks")
    op.drop_index(
        "ix_kb_chunks_embedding",
        table_name="kb_chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("kb_chunks")
    op.drop_index(op.f("ix_channels_tenant_id"), table_name="channels")
    op.drop_table("channels")
    op.drop_index(op.f("ix_catalog_sources_tenant_id"), table_name="catalog_sources")
    op.drop_table("catalog_sources")
    op.drop_index(op.f("ix_bot_profiles_tenant_id"), table_name="bot_profiles")
    op.drop_table("bot_profiles")
    op.drop_table("tenants")
