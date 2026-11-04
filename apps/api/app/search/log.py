import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SearchLog
from app.search.types import KbHit, ProductFilters, ProductHit


async def record_search(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    kind: str,
    query: str,
    lang: str | None,
    items: Sequence[ProductHit] | Sequence[KbHit],
    latency_ms: int,
    filters: ProductFilters | None = None,
    conversation_id: uuid.UUID | None = None,
) -> None:
    results: list[dict[str, Any]] = []
    in_stock: bool | None = None
    for item in items:
        entry: dict[str, Any] = {"id": str(item.id), "reasons": list(item.reasons)}
        if item.score is not None:
            entry["score"] = round(item.score, 4)
        if isinstance(item, ProductHit):
            entry["sku"] = item.sku
            in_stock = bool(in_stock) or item.in_stock
        else:
            entry["source"] = item.source
        results.append(entry)
    if kind == "product" and not items:
        in_stock = False
    session.add(
        SearchLog(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            kind=kind,
            query=query,
            lang=lang,
            filters=filters.as_dict() if filters else {},
            results=results,
            result_count=len(items),
            has_in_stock=in_stock,
            latency_ms=latency_ms,
        )
    )
    await session.flush()
