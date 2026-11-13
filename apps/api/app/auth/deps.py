import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import ACCESS_COOKIE
from app.auth.otp import OtpService
from app.auth.senders import CodeSender, build_code_sender
from app.auth.tokens import InvalidTokenError, RefreshStore, decode_access_token, is_revoked
from app.auth.users import load_user
from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.session import tenant_session
from app.models import AuditLog
from app.seed import DEMO_TENANT_ID

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEMO_WRITABLE = re.compile(
    r"^/(sandbox/chat|conversations/[^/]+/(takeover|release|reply|draft)"
    r"|leads/[0-9a-f-]{36}|notifications/[^/]+/read|automations/[a-z_]+/preview)$"
)


def get_otp() -> OtpService:
    return OtpService(get_redis(), get_settings())


@lru_cache
def get_code_sender() -> CodeSender:
    return build_code_sender(get_settings())


def get_refresh_store() -> RefreshStore:
    return RefreshStore(get_redis(), get_settings())


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    home_tenant_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    actor_id: uuid.UUID | None = None


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")


def demo_read_only(principal: Principal, request: Request) -> bool:
    return (
        principal.tenant_id == DEMO_TENANT_ID
        and principal.actor_id is None
        and get_settings().demo_enabled
        and request.method not in SAFE_METHODS
        and not DEMO_WRITABLE.match(request.url.path)
    )


async def current_user(
    request: Request,
    token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> Principal:
    if not token:
        raise _unauthorized()
    try:
        claims = decode_access_token(token, get_settings())
    except InvalidTokenError as exc:
        raise _unauthorized() from exc
    if await is_revoked(get_redis(), claims):
        raise _unauthorized()

    user = await load_user(claims.user_id, claims.tenant_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    if user.suspended and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "shop_suspended")
    if claims.impersonating:
        if user.role != "admin":
            raise _unauthorized()
        return Principal(user.id, user.tenant_id, claims.impersonating, "owner", actor_id=user.id)
    principal = Principal(user.id, user.tenant_id, user.tenant_id, user.role)
    if demo_read_only(principal, request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "demo_read_only")
    return principal


CurrentUser = Annotated[Principal, Depends(current_user)]


def require_role(*roles: str) -> Callable[[Principal], Awaitable[Principal]]:
    async def dependency(principal: CurrentUser) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
        return principal

    return dependency


async def tenant_db(principal: CurrentUser, request: Request) -> AsyncIterator[AsyncSession]:
    async with tenant_session(principal.tenant_id) as session:
        if principal.actor_id and request.method not in SAFE_METHODS:
            session.add(
                AuditLog(
                    tenant_id=principal.tenant_id,
                    actor_id=principal.actor_id,
                    action=f"{request.method} {request.url.path}",
                    details={"impersonation": True},
                )
            )
        yield session


TenantDb = Annotated[AsyncSession, Depends(tenant_db, scope="function")]
