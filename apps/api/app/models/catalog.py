import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin

EMBEDDING_DIM = 1024

PRODUCT_TSV = (
    "setweight(to_tsvector('russian', coalesce(name, '')), 'A') || "
    "setweight(to_tsvector('russian', coalesce(description, '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(synonyms, '')), 'A')"
)
SKU_NORM = r"upper(regexp_replace(sku, '[\s-]+', '', 'g'))"


class CatalogSource(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "catalog_sources"
    __table_args__ = (
        CheckConstraint(
            "type IN ('excel', 'csv', 'gsheet', 'moysklad', 'onec', 'kaspi')", name="type"
        ),
    )

    type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(200))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    column_map: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    schedule: Mapped[str | None] = mapped_column(String(64))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestJob(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'done', 'failed')", name="status"
        ),
        CheckConstraint("file_type IN ('xlsx', 'csv')", name="file_type"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_sources.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    file_key: Mapped[str | None] = mapped_column(String(500))
    file_name: Mapped[str | None] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(8))
    rows_total: Mapped[int | None] = mapped_column(Integer)
    rows_done: Mapped[int] = mapped_column(Integer, server_default="0")
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql_text("'{}'::jsonb"))
    errors: Mapped[list[Any]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price"),
        CheckConstraint("stock >= 0", name="stock"),
        UniqueConstraint("tenant_id", "sku_norm"),
        Index(
            "uq_products_tenant_id_name_hash",
            "tenant_id",
            "name_hash",
            unique=True,
            postgresql_where=sql_text("sku_norm IS NULL"),
        ),
        Index("ix_products_tenant_id_price", "tenant_id", "price"),
        Index("ix_products_tenant_id_stock", "tenant_id", "stock"),
        Index("ix_products_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_products_sku_norm_trgm",
            "sku_norm",
            postgresql_using="gin",
            postgresql_ops={"sku_norm": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_sources.id", ondelete="SET NULL"), index=True
    )
    sku: Mapped[str | None] = mapped_column(String(100))
    sku_norm: Mapped[str | None] = mapped_column(String(100), Computed(SKU_NORM, persisted=True))
    name: Mapped[str] = mapped_column(String(500))
    name_hash: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(200))
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sql_text("'{}'::jsonb")
    )
    synonyms: Mapped[str | None] = mapped_column(Text)
    price: Mapped[int | None] = mapped_column(BigInteger)
    stock: Mapped[int | None] = mapped_column(Integer)
    images: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_stale: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed(PRODUCT_TSV, persisted=True))


class KbChunk(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_kb_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    source: Mapped[str] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_stale: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('russian', coalesce(title, '') || ' ' || text)", persisted=True),
    )
