import hashlib
import hmac
import secrets

from redis.asyncio import Redis

from app.auth.identity import Identity
from app.core.config import Settings


class OtpError(Exception):
    pass


class TooManyRequestsError(OtpError):
    pass


class TooManyAttemptsError(OtpError):
    pass


class CodeExpiredError(OtpError):
    pass


class WrongCodeError(OtpError):
    pass


class OtpService:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.ttl = settings.otp_ttl
        self.max_attempts = settings.otp_max_attempts
        self.max_requests = settings.otp_max_requests
        self._pepper = settings.jwt_secret.get_secret_value().encode()

    @staticmethod
    def _keys(identity: Identity) -> tuple[str, str, str]:
        base = f"otp:{identity.key}"
        return f"{base}:code", f"{base}:attempts", f"{base}:requests"

    def _hash(self, identity: Identity, code: str) -> str:
        return hmac.new(self._pepper, f"{identity.key}:{code}".encode(), hashlib.sha256).hexdigest()

    async def issue(self, identity: Identity) -> str:
        code_key, attempts_key, requests_key = self._keys(identity)
        requests = await self.redis.incr(requests_key)
        if requests == 1:
            await self.redis.expire(requests_key, self.ttl)
        if requests > self.max_requests:
            raise TooManyRequestsError

        code = f"{secrets.randbelow(10**6):06d}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(code_key, self._hash(identity, code), ex=self.ttl)
            pipe.delete(attempts_key)
            await pipe.execute()
        return code

    async def verify(self, identity: Identity, code: str, *, consume: bool = True) -> None:
        code_key, attempts_key, _ = self._keys(identity)
        stored = await self.redis.get(code_key)
        if stored is None:
            raise CodeExpiredError

        attempts = await self.redis.incr(attempts_key)
        if attempts == 1:
            await self.redis.expire(attempts_key, self.ttl)
        if attempts > self.max_attempts:
            await self.redis.delete(code_key)
            raise TooManyAttemptsError

        if not hmac.compare_digest(stored, self._hash(identity, code)):
            raise WrongCodeError
        if consume:
            await self.redis.delete(code_key, attempts_key)
        else:
            await self.redis.decr(attempts_key)
