import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass

import jwt
from redis.asyncio import Redis

from app.core.config import Settings

ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    impersonating: uuid.UUID | None = None
    token_id: str | None = None
    expires_at: int = 0


def create_access_token(claims: AccessClaims, settings: Settings) -> str:
    now = int(time.time())
    payload: dict[str, object] = {
        "sub": str(claims.user_id),
        "tid": str(claims.tenant_id),
        "role": claims.role,
        "typ": "access",
        "jti": secrets.token_urlsafe(12),
        "iat": now,
        "exp": now + settings.access_token_ttl,
    }
    if claims.impersonating:
        payload["imp"] = str(claims.impersonating)
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "tid", "role", "exp", "typ"]},
        )
        if payload["typ"] != "access":
            raise InvalidTokenError
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tid"]),
            role=payload["role"],
            impersonating=uuid.UUID(payload["imp"]) if payload.get("imp") else None,
            token_id=payload.get("jti"),
            expires_at=int(payload["exp"]),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError from exc


@dataclass(frozen=True)
class RefreshSession:
    user_id: uuid.UUID
    tenant_id: uuid.UUID


class RefreshStore:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.ttl = settings.refresh_token_ttl

    @staticmethod
    def _key(token: str) -> str:
        return "auth:refresh:" + hashlib.sha256(token.encode()).hexdigest()

    async def issue(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
        token = secrets.token_urlsafe(32)
        value = json.dumps({"uid": str(user_id), "tid": str(tenant_id)})
        await self.redis.set(self._key(token), value, ex=self.ttl)
        return token

    async def consume(self, token: str) -> RefreshSession | None:
        raw = await self.redis.getdel(self._key(token))
        if raw is None:
            return None
        data = json.loads(raw)
        return RefreshSession(uuid.UUID(data["uid"]), uuid.UUID(data["tid"]))

    async def revoke(self, token: str) -> None:
        await self.redis.delete(self._key(token))


def _revoked_key(token_id: str) -> str:
    return f"auth:revoked:{token_id}"


async def revoke_access_token(redis: Redis, token: str | None, settings: Settings) -> None:
    if not token:
        return
    try:
        claims = decode_access_token(token, settings)
    except InvalidTokenError:
        return
    left = claims.expires_at - int(time.time())
    if claims.token_id and left > 0:
        await redis.set(_revoked_key(claims.token_id), "1", ex=left)


async def is_revoked(redis: Redis, claims: AccessClaims) -> bool:
    return bool(claims.token_id and await redis.exists(_revoked_key(claims.token_id)))
