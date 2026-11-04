import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.deps import Principal, require_role
from app.db.session import tenant_session
from app.mlclient import MLClient, get_ml_client
from app.models import Tenant
from app.search import ProductFilters, search_kb, search_products

router = APIRouter(prefix="/debug", tags=["debug"])

Admin = Annotated[Principal, Depends(require_role("admin"))]


class ProductOut(BaseModel):
    id: uuid.UUID
    sku: str | None
    name: str
    category: str | None
    price: int | None
    stock: int | None
    reasons: list[str]
    ranks: dict[str, int]
    rrf: float
    score: float | None


class KbOut(BaseModel):
    id: uuid.UUID
    source: str
    title: str | None
    text: str
    reasons: list[str]
    ranks: dict[str, int]
    rrf: float
    score: float | None


class DebugSearchOut(BaseModel):
    query: str
    lang: str | None
    filters: dict[str, Any]
    latency_ms: int
    candidates: dict[str, int]
    products: list[ProductOut]
    kb: list[KbOut]


@router.get("/search")
async def debug_search(
    admin: Admin,
    ml: Annotated[MLClient, Depends(get_ml_client)],
    q: Annotated[str, Query(min_length=1, max_length=500)],
    tenant_id: uuid.UUID,
    price_min: int | None = None,
    price_max: int | None = None,
    in_stock: bool = False,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 5,
    rerank: bool = True,
) -> DebugSearchOut:
    filters = ProductFilters(price_min, price_max, in_stock, category)
    async with tenant_session(tenant_id) as session:
        if await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant_not_found")
        products = await search_products(
            session, q, filters, ml=ml, limit=limit, use_reranker=rerank, record=False
        )
        kb = await search_kb(session, q, ml=ml, record=False)
    return DebugSearchOut(
        query=q,
        lang=products.lang,
        filters=filters.as_dict(),
        latency_ms=products.latency_ms + kb.latency_ms,
        candidates=products.candidates,
        products=[
            ProductOut(**{**hit.__dict__, "reasons": list(hit.reasons)}) for hit in products.items
        ],
        kb=[KbOut(**{**hit.__dict__, "reasons": list(hit.reasons)}) for hit in kb.items],
    )
