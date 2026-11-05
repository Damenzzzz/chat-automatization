import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import set_access_cookie
from app.auth.deps import CurrentUser, Principal, require_role
from app.auth.tokens import AccessClaims, create_access_token
from app.billing.pricing import load_pricing
from app.cli import SATUSHY_TENANT_ID
from app.core.config import get_settings
from app.db.session import tenant_session
from app.models import AuditLog, PricingSettings, Tenant

router = APIRouter(prefix="/admin", tags=["admin"])

Admin = Annotated[Principal, Depends(require_role("admin"))]


class ModelPriceIn(BaseModel):
    input_per_m: Decimal = Field(ge=0)
    output_per_m: Decimal = Field(ge=0)


class PricingIn(BaseModel):
    markup: Decimal = Field(default=Decimal(3), ge=3, max_digits=6, decimal_places=3)
    kzt_per_usd: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=4)
    model_prices: dict[str, ModelPriceIn] = Field(default_factory=dict)


class PricingOut(BaseModel):
    markup: Decimal
    kzt_per_usd: Decimal
    model_prices: dict[str, ModelPriceIn]


async def _pricing_out(session: AsyncSession) -> PricingOut:
    pricing = await load_pricing(session)
    return PricingOut(
        markup=pricing.markup,
        kzt_per_usd=pricing.kzt_per_usd,
        model_prices={
            model: ModelPriceIn(input_per_m=p.input_per_m, output_per_m=p.output_per_m)
            for model, p in pricing.model_prices.items()
        },
    )


async def _save_pricing(tenant_id: uuid.UUID, body: PricingIn, admin: Principal) -> PricingOut:
    values = {
        "markup": body.markup,
        "kzt_per_usd": body.kzt_per_usd,
        "model_prices": {
            model: {"input_per_m": str(p.input_per_m), "output_per_m": str(p.output_per_m)}
            for model, p in body.model_prices.items()
        },
    }
    async with tenant_session(tenant_id) as session:
        if await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant_not_found")
        await session.execute(
            insert(PricingSettings)
            .values(tenant_id=tenant_id, **values)
            .on_conflict_do_update(index_elements=[PricingSettings.tenant_id], set_=values)
        )
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_id=admin.user_id,
                action="pricing.update",
                details={"markup": str(body.markup), "kzt_per_usd": str(body.kzt_per_usd)},
            )
        )
        await session.flush()
        return await _pricing_out(session)


@router.get("/pricing")
async def get_pricing(admin: Admin) -> PricingOut:
    async with tenant_session(SATUSHY_TENANT_ID) as session:
        return await _pricing_out(session)


@router.put("/pricing")
async def put_pricing(body: PricingIn, admin: Admin) -> PricingOut:
    return await _save_pricing(SATUSHY_TENANT_ID, body, admin)


@router.put("/tenants/{tenant_id}/pricing")
async def put_tenant_pricing(tenant_id: uuid.UUID, body: PricingIn, admin: Admin) -> PricingOut:
    return await _save_pricing(tenant_id, body, admin)


class ImpersonationOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str


@router.post("/impersonate/{tenant_id}")
async def impersonate(tenant_id: uuid.UUID, admin: Admin, response: Response) -> ImpersonationOut:
    async with tenant_session(tenant_id) as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant_not_found")
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_id=admin.user_id,
                action="impersonation.start",
                details={"admin_tenant_id": str(admin.home_tenant_id)},
            )
        )
        name = tenant.name

    claims = AccessClaims(admin.user_id, admin.home_tenant_id, admin.role, impersonating=tenant_id)
    set_access_cookie(response, create_access_token(claims, get_settings()), get_settings())
    return ImpersonationOut(tenant_id=tenant_id, tenant_name=name)


@router.delete("/impersonate", status_code=status.HTTP_204_NO_CONTENT)
async def stop_impersonation(principal: CurrentUser, response: Response) -> None:
    if principal.actor_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not_impersonating")
    async with tenant_session(principal.tenant_id) as session:
        session.add(
            AuditLog(
                tenant_id=principal.tenant_id,
                actor_id=principal.actor_id,
                action="impersonation.stop",
            )
        )
    claims = AccessClaims(principal.actor_id, principal.home_tenant_id, "admin")
    set_access_cookie(response, create_access_token(claims, get_settings()), get_settings())
