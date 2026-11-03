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
from app.auth.tokens import InvalidTokenError, RefreshStore, decode_access_token
from app.auth.users import load_user
from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.session import tenant_session
from app.models import AuditLog

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


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


async def current_user(
    token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
) -> Principal:
    if not token:
        raise _unauthorized()
    try:
        claims = decode_access_token(token, get_settings())
    except InvalidTokenError as exc:
        raise _unauthorized() from exc

    user = await load_user(claims.user_id, claims.tenant_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    if claims.impersonating:
        if user.role != "admin":
            raise _unauthorized()
        return Principal(user.id, user.tenant_id, claims.impersonating, "owner", actor_id=user.id)
    return Principal(user.id, user.tenant_id, user.tenant_id, user.role)


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
