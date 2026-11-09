import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.deps import CurrentUser, TenantDb
from app.models import Tenant
from app.seed import DEMO_TENANT_ID

router = APIRouter(tags=["auth"])


class MeOut(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    tenant_name: str
    role: str
    impersonated_by: uuid.UUID | None
    demo: bool = False


@router.get("/me")
async def me(principal: CurrentUser, db: TenantDb) -> MeOut:
    tenant = await db.scalar(select(Tenant).where(Tenant.id == principal.tenant_id))
    assert tenant is not None  # noqa: S101
    return MeOut(
        user_id=principal.user_id,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        role=principal.role,
        impersonated_by=principal.actor_id,
        demo=tenant.id == DEMO_TENANT_ID,
    )
