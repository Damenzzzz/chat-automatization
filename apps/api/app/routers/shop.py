import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentUser, Principal, TenantDb, require_role
from app.models import Tenant

router = APIRouter(prefix="/shop", tags=["shop"])

Owner = Annotated[Principal, Depends(require_role("owner"))]
ONBOARDING_STEPS = 5


class ShopLinks(BaseModel):
    instagram: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=300)
    two_gis: str | None = Field(default=None, max_length=300)
    kaspi: str | None = Field(default=None, max_length=300)


class ShopOut(BaseModel):
    id: uuid.UUID
    name: str
    niche: str | None
    city: str | None
    status: str
    links: ShopLinks
    onboarding_step: int


class ShopIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    niche: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    links: ShopLinks | None = None
    onboarding_step: int | None = Field(default=None, ge=1, le=ONBOARDING_STEPS)
    onboarding_done: bool | None = None


def shop_out(tenant: Tenant) -> ShopOut:
    return ShopOut(
        id=tenant.id,
        name=tenant.name,
        niche=tenant.niche,
        city=tenant.city,
        status=tenant.status,
        links=ShopLinks(**tenant.links),
        onboarding_step=tenant.onboarding_step,
    )


async def load_tenant(db: TenantDb, tenant_id: uuid.UUID) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    assert tenant is not None  # noqa: S101
    return tenant


@router.get("")
async def get_shop(principal: CurrentUser, db: TenantDb) -> ShopOut:
    return shop_out(await load_tenant(db, principal.tenant_id))


@router.patch("")
async def update_shop(body: ShopIn, principal: Owner, db: TenantDb) -> ShopOut:
    tenant = await load_tenant(db, principal.tenant_id)
    for name, value in body.model_dump(
        exclude_unset=True, exclude={"links", "onboarding_done"}
    ).items():
        if name == "name" and value is None:
            continue
        setattr(tenant, name, value)
    if body.links is not None:
        tenant.links = body.links.model_dump(exclude_none=True)
    if body.onboarding_done and tenant.status == "onboarding":
        tenant.status = "active"
    await db.flush()
    return shop_out(tenant)
