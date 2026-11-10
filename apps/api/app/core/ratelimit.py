import time
from typing import Any

from fastapi import HTTPException, status


async def over_limit(redis: Any, key: str, count: int, window: int) -> bool:
    bucket = f"ratelimit:{key}:{int(time.time() // window)}"
    pipe = redis.pipeline(transaction=True)
    pipe.incr(bucket)
    pipe.expire(bucket, window * 2)
    hits, _ = await pipe.execute()
    return bool(hits > count)


async def limit(
    redis: Any, key: str, count: int, window: int, headers: dict[str, str] | None = None
) -> None:
    if await over_limit(redis, key, count, window):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too_many_requests",
            headers={**(headers or {}), "Retry-After": str(window)},
        )
