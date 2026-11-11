import uuid

import structlog
from redis.exceptions import RedisError

from app.core.redis import get_redis

log = structlog.get_logger()


def cabinet_channel(tenant_id: uuid.UUID | str) -> str:
    return f"cabinet:{tenant_id}"


async def poke(tenant_id: uuid.UUID | str) -> None:
    try:
        await get_redis().publish(cabinet_channel(tenant_id), "1")
    except RedisError as exc:
        log.warning("cabinet.poke_failed", error=str(exc))
