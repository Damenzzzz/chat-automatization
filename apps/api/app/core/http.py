from collections.abc import AsyncIterator

import httpx


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        yield client
