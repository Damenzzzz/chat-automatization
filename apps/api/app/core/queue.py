from functools import lru_cache
from typing import Any, Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings


class Queue(Protocol):
    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None: ...


class ArqQueue:
    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._pool: ArqRedis | None = None

    async def enqueue(self, function: str, *args: Any, job_id: str | None = None) -> None:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(self.redis_url))
        await self._pool.enqueue_job(function, *args, _job_id=job_id)


@lru_cache
def get_queue() -> Queue:
    return ArqQueue(get_settings().redis_url)
