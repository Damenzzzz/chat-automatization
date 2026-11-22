import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ColumnElement, func, or_, select, update

from app.auth.deps import Principal, TenantDb, require_role
from app.models import Product

router = APIRouter(prefix="/products", tags=["catalog"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
Owner = Annotated[Principal, Depends(require_role("owner"))]


class CatalogProduct(BaseModel):
    id: uuid.UUID
    name: str
    sku: str | None
    category: str | None
    description: str | None
    attributes: dict[str, Any]
    price: int | None
    stock: int | None
    images: list[str]
    indexed: bool
    updated_at: datetime


class ProductList(BaseModel):
    total: int
    items: list[CatalogProduct]


class ProductPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: int | None = Field(default=None, ge=0, le=1_000_000_000)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)
    is_active: bool | None = None


COLUMNS = (
    Product.id,
    Product.name,
    Product.sku,
    Product.category,
    Product.description,
    Product.attributes,
    Product.price,
    Product.stock,
    Product.images,
    (Product.embedding.is_not(None) & Product.embedding_stale.is_(False)).label("indexed"),
    Product.updated_at,
)


@router.get("")
async def list_products(
    principal: Member,
    db: TenantDb,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductList:
    where: list[ColumnElement[bool]] = [Product.is_active.is_(True)]
    if q and q.strip():
        needle = q.strip()
        where.append(
            or_(
                Product.name.icontains(needle, autoescape=True),
                Product.sku.icontains(needle, autoescape=True),
            )
        )
    total = await db.scalar(select(func.count()).select_from(Product).where(*where))
    rows = await db.execute(
        select(*COLUMNS)
        .where(*where)
        .order_by(Product.name, Product.id)
        .limit(limit)
        .offset(offset)
    )
    return ProductList(
        total=total or 0,
        items=[CatalogProduct.model_validate(r, from_attributes=True) for r in rows],
    )


@router.patch("/{product_id}")
async def update_product(
    product_id: uuid.UUID, body: ProductPatch, principal: Owner, db: TenantDb
) -> CatalogProduct:
    changes = body.model_dump(include=body.model_fields_set)
    if changes.get("is_active", True) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "is_active_required")
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing_to_update")
    updated = await db.scalar(
        update(Product)
        .where(Product.id == product_id)
        .values(**changes, updated_at=func.now())
        .returning(Product.id)
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "product_not_found")
    row = (await db.execute(select(*COLUMNS).where(Product.id == product_id))).one()
    return CatalogProduct.model_validate(row, from_attributes=True)
