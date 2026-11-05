import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import HTTPException, Request, status

from app.channels.types import ChannelError

Sleep = Callable[[float], Awaitable[None]]
MAX_RETRY_AFTER = 10.0
MAX_WEBHOOK_BODY = 2 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class ChannelHttp:
    """Ошибки без URL и заголовков: в них токены каналов."""

    def __init__(
        self,
        service: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.service = service
        self.transport = transport
        self.sleep = sleep
        self.timeout = timeout
        self.max_retries = max_retries

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport, follow_redirects=True
        )

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async with self._client() as http:
            for attempt in range(self.max_retries + 1):
                last = attempt == self.max_retries
                try:
                    response = await http.request(method, url, **kwargs)
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                    if last:
                        raise ChannelError(f"{self.service}: сеть недоступна") from None
                    await self.sleep(0.5 * 2**attempt)
                    continue
                except httpx.HTTPError as exc:
                    kind = type(exc).__name__
                    raise ChannelError(f"{self.service}: запрос не выполнен ({kind})") from None
                if last or (response.status_code != 429 and response.status_code < 500):
                    return response
                await self.sleep(self._delay(response, attempt))
        raise AssertionError("unreachable")

    def _delay(self, response: httpx.Response, attempt: int) -> float:
        try:
            value = float(response.headers.get("retry-after", ""))
        except ValueError:
            value = 0.5 * 2**attempt
        return min(MAX_RETRY_AFTER, value)

    async def download(self, url: str, *, headers: dict[str, str] | None = None) -> bytes:
        chunks: list[bytes] = []
        size = 0
        try:
            async with self._client() as http, http.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise ChannelError(
                        f"{self.service}: файл не скачан (HTTP {response.status_code})"
                    )
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise ChannelError(f"{self.service}: файл слишком большой")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            kind = type(exc).__name__
            raise ChannelError(f"{self.service}: файл не скачан ({kind})") from None
        return b"".join(chunks)


async def read_body(request: Request, limit: int = MAX_WEBHOOK_BODY) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "body_too_large")
    return bytes(body)
