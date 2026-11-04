import time
import uuid

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.embedding_text import product_text
from app.core.config import get_settings
from app.mlclient import MLError, get_ml_client
from app.models import Product
from app.search.candidates import (
    enable_iterative_scan,
    fts_products,
    passes,
    sku_codes,
    sku_products,
    vector_products,
)
from app.search.fusion import Fused, rrf
from app.search.types import ProductFilters, ProductHit, SearchML, SearchResult

log = structlog.get_logger()


async def current_tenant(session: AsyncSession) -> uuid.UUID:
    value = await session.scalar(text("SELECT current_setting('app.tenant_id', true)"))
    if not value:
        raise RuntimeError("поиск вызывается только внутри tenant_session")
    return uuid.UUID(value)


async def candidate_lists(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    query: str,
    filters: ProductFilters,
    ml: SearchML,
) -> tuple[dict[str, list[uuid.UUID]], set[uuid.UUID]]:
    settings = get_settings()
    limit = settings.search_candidates
    lists: dict[str, list[uuid.UUID]] = {}
    try:
        [vector] = await ml.embed([query], "query")
    except MLError as exc:
        log.warning("search.embed_failed", error=str(exc))
    else:
        await enable_iterative_scan(session, settings.search_ef_search)
        lists["vector"] = await vector_products(session, tenant_id, vector, filters, limit)
    lists["fts"] = await fts_products(session, tenant_id, query, filters, limit)
    exact: set[uuid.UUID] = set()
    codes = sku_codes(query)
    if codes:
        found = await sku_products(session, tenant_id, codes, filters, limit)
        lists["sku"] = [item_id for item_id, _ in found]
        exact = {item_id for item_id, is_exact in found if is_exact}
    return lists, exact


def _hit(product: Product, fused: Fused, score: float | None = None) -> ProductHit:
    return ProductHit(
        id=product.id,
        sku=product.sku,
        name=product.name,
        category=product.category,
        price=product.price,
        stock=product.stock,
        reasons=tuple(r for r in ("vector", "fts", "sku") if r in fused.ranks),
        ranks=dict(fused.ranks),
        rrf=fused.score,
        score=score,
    )


async def rerank(ml: SearchML, query: str, documents: list[str]) -> list[float] | None:
    if not documents:
        return []
    try:
        return await ml.rerank(query, documents)
    except MLError as exc:
        log.warning("search.rerank_failed", error=str(exc))
        return None


async def search_products(
    session: AsyncSession,
    query: str,
    filters: ProductFilters | None = None,
    *,
    ml: SearchML | None = None,
    limit: int = 5,
    use_reranker: bool = True,
) -> SearchResult[ProductHit]:
    started = time.perf_counter()
    settings = get_settings()
    filters = filters or ProductFilters()
    tenant_id = await current_tenant(session)
    ml = ml or get_ml_client()
    lists, exact = await candidate_lists(session, tenant_id, query, filters, ml)
    fused = rrf(lists, settings.search_rrf_k)

    rows = await session.scalars(
        select(Product).where(Product.id.in_([f.id for f in fused]), Product.is_active)
    )
    products = {p.id: p for p in rows}
    pool = [
        f
        for f in fused
        if f.id in products
        and passes(filters, products[f.id].price, products[f.id].stock, products[f.id].category)
    ]
    pool = pool[: settings.search_rerank_top]

    scores: list[float] | None = None
    if use_reranker:
        texts = [
            product_text(p.name, p.category, p.description, p.attributes, p.synonyms)
            for p in (products[f.id] for f in pool)
        ]
        scores = await rerank(ml, query, texts)
    ranked = [(f, scores[i] if scores else None) for i, f in enumerate(pool)]
    if scores:
        ranked.sort(key=lambda item: -(item[1] or 0.0))
    ranked.sort(key=lambda item: item[0].id not in exact)
    hits = [_hit(products[f.id], f, score) for f, score in ranked[:limit]]
    return SearchResult(
        items=hits,
        lang=None,
        latency_ms=round((time.perf_counter() - started) * 1000),
        candidates={name: len(ids) for name, ids in lists.items()},
    )
