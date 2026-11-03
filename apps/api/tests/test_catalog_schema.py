import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


async def _tenant(conn: AsyncConnection) -> uuid.UUID:
    tenant_id: uuid.UUID = await conn.scalar(
        text("INSERT INTO tenants (name) VALUES ('Каталог') RETURNING id")
    )
    return tenant_id


async def test_sku_norm_and_tsv(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        tenant_id = await _tenant(conn)
        row = (
            await conn.execute(
                text(
                    "INSERT INTO products (tenant_id, sku, name, description, synonyms) "
                    "VALUES (:t, 'ab-12 3c', 'Букет пионов', 'Розовые пионы', 'гүлдер шоғы') "
                    "RETURNING sku_norm, embedding_stale, "
                    "tsv @@ plainto_tsquery('russian', 'пион') AS ru, "
                    "tsv @@ plainto_tsquery('simple', 'гүлдер') AS kk"
                ),
                {"t": tenant_id},
            )
        ).one()

    assert row.sku_norm == "AB123C"
    assert row.embedding_stale is True
    assert row.ru and row.kk


async def test_sku_norm_unique_per_tenant(owner_engine: AsyncEngine) -> None:
    insert = text("INSERT INTO products (tenant_id, sku, name) VALUES (:t, :sku, 'x')")
    async with owner_engine.begin() as conn:
        tenant_a, tenant_b = await _tenant(conn), await _tenant(conn)
        await conn.execute(insert, {"t": tenant_a, "sku": "P-100"})
        await conn.execute(insert, {"t": tenant_b, "sku": "P-100"})

    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(insert, {"t": tenant_a, "sku": "p 100"})


async def test_catalog_indexes_exist(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'products'")
        )
        defs = {r.indexname: r.indexdef for r in rows}

    assert "hnsw (embedding vector_cosine_ops)" in defs["ix_products_embedding"]
    assert "gin (tsv)" in defs["ix_products_tsv"]
    assert "gin_trgm_ops" in defs["ix_products_sku_norm_trgm"]
    assert "gin_trgm_ops" in defs["ix_products_name_trgm"]
    assert "(tenant_id, price)" in defs["ix_products_tenant_id_price"]
    assert "(tenant_id, stock)" in defs["ix_products_tenant_id_stock"]
    assert "UNIQUE" in defs["uq_products_tenant_id_sku_norm"]
