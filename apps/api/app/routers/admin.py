import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.cookies import set_access_cookie
from app.auth.deps import CurrentUser, Principal, require_role
from app.auth.tokens import AccessClaims, create_access_token
from app.core.config import get_settings
from app.db.session import tenant_session
from app.models import AuditLog, Tenant

router = APIRouter(prefix="/admin", tags=["admin"])

Admin = Annotated[Principal, Depends(require_role("admin"))]


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
