import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.search.types import ProductFilters


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def filter_sql(filters: ProductFilters) -> tuple[str, dict[str, Any]]:
    parts = ["p.is_active"]
    params: dict[str, Any] = {}
    if filters.price_min is not None:
        parts.append("p.price >= :price_min")
        params["price_min"] = filters.price_min
    if filters.price_max is not None:
        parts.append("p.price <= :price_max")
        params["price_max"] = filters.price_max
    if filters.in_stock:
        parts.append("(p.stock IS NULL OR p.stock > 0)")
    if filters.category:
        parts.append("lower(p.category) = lower(:category)")
        params["category"] = filters.category
    return " AND ".join(parts), params


def passes(
    filters: ProductFilters, price: int | None, stock: int | None, category: str | None
) -> bool:
    if filters.price_min is not None and (price is None or price < filters.price_min):
        return False
    if filters.price_max is not None and (price is None or price > filters.price_max):
        return False
    if filters.in_stock and stock is not None and stock <= 0:
        return False
    return not (filters.category and (category or "").lower() != filters.category.lower())


async def enable_iterative_scan(session: AsyncSession, ef_search: int) -> None:
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))


async def vector_products(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    vector: list[float],
    filters: ProductFilters,
    limit: int,
) -> list[uuid.UUID]:
    where, params = filter_sql(filters)
    rows = await session.execute(
        text(
            "WITH c AS MATERIALIZED ("  # noqa: S608
            " SELECT p.id, p.embedding <=> CAST(:v AS vector) AS d FROM products p"
            f" WHERE p.tenant_id = :t AND p.embedding IS NOT NULL AND {where}"
            " ORDER BY d LIMIT :limit"
            ") SELECT id FROM c ORDER BY d"
        ),
        {"v": vector_literal(vector), "t": tenant_id, "limit": limit, **params},
    )
    return list(rows.scalars())


async def vector_kb(
    session: AsyncSession, tenant_id: uuid.UUID, vector: list[float], limit: int
) -> list[uuid.UUID]:
    rows = await session.execute(
        text(
            "WITH c AS MATERIALIZED ("
            " SELECT k.id, k.embedding <=> CAST(:v AS vector) AS d FROM kb_chunks k"
            " WHERE k.tenant_id = :t AND k.embedding IS NOT NULL ORDER BY d LIMIT :limit"
            ") SELECT id FROM c ORDER BY d"
        ),
        {"v": vector_literal(vector), "t": tenant_id, "limit": limit},
    )
    return list(rows.scalars())
