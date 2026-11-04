import re
import uuid
from itertools import pairwise
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.normalize import sku_norm
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


ANY_TSQUERY = (
    "CAST(concat_ws(' | ',"
    " nullif(replace(websearch_to_tsquery('russian', :q)::text, ' & ', ' | '), ''),"
    " nullif(replace(websearch_to_tsquery('simple', :q)::text, ' & ', ' | '), '')"
    ") AS tsquery)"
)


async def fts_products(
    session: AsyncSession, tenant_id: uuid.UUID, query: str, filters: ProductFilters, limit: int
) -> list[uuid.UUID]:
    where, params = filter_sql(filters)
    rows = await session.execute(
        text(
            f"WITH q AS (SELECT {ANY_TSQUERY} AS tsq)"  # noqa: S608
            " SELECT p.id FROM products p, q"
            f" WHERE p.tenant_id = :t AND p.tsv @@ q.tsq AND {where}"
            " ORDER BY ts_rank_cd(p.tsv, q.tsq) DESC, p.id LIMIT :limit"
        ),
        {"q": query, "t": tenant_id, "limit": limit, **params},
    )
    return list(rows.scalars())


async def fts_kb(
    session: AsyncSession, tenant_id: uuid.UUID, query: str, limit: int
) -> list[uuid.UUID]:
    rows = await session.execute(
        text(
            f"WITH q AS (SELECT {ANY_TSQUERY} AS tsq)"  # noqa: S608
            " SELECT k.id FROM kb_chunks k, q WHERE k.tenant_id = :t AND k.tsv @@ q.tsq"
            " ORDER BY ts_rank_cd(k.tsv, q.tsq) DESC, k.id LIMIT :limit"
        ),
        {"q": query, "t": tenant_id, "limit": limit},
    )
    return list(rows.scalars())


TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі][\w\-/.]*")
LATIN = re.compile(r"[A-Za-z]")


def _looks_like_sku(token: str) -> bool:
    if not any(c.isdigit() for c in token):
        return False
    if token.isdigit():
        return len(token) >= 7
    return bool(LATIN.search(token)) or "-" in token.strip("-")


def sku_codes(query: str) -> list[str]:
    tokens = [t.rstrip(".,/") for t in TOKEN.findall(query)]
    candidates = list(tokens)
    for left, right in pairwise(tokens):
        if left.isalpha() and LATIN.match(left) and len(left) <= 6 and right.isdigit():
            candidates.append(left + right)
    codes: list[str] = []
    for token in candidates:
        code = sku_norm(token) if _looks_like_sku(token) else None
        if code and code not in codes:
            codes.append(code)
    return codes


async def sku_products(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    codes: list[str],
    filters: ProductFilters,
    limit: int,
) -> list[tuple[uuid.UUID, bool]]:
    if not codes:
        return []
    where, params = filter_sql(filters)
    rows = await session.execute(
        text(
            "SELECT p.id, bool_or(p.sku_norm = c) AS exact,"  # noqa: S608
            " max(CASE WHEN p.sku_norm = c THEN 2 ELSE similarity(p.sku_norm, c) END) AS s"
            " FROM products p, unnest(CAST(:codes AS text[])) AS c"
            f" WHERE p.tenant_id = :t AND (p.sku_norm = c OR p.sku_norm % c) AND {where}"
            " GROUP BY p.id ORDER BY s DESC, p.id LIMIT :limit"
        ),
        {"codes": codes, "t": tenant_id, "limit": limit, **params},
    )
    return [(row.id, row.exact) for row in rows]
