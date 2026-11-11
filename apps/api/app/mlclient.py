import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import httpx
import structlog

from app.core.config import get_settings

log = structlog.get_logger()

EMBEDDING_DIM = 1024
SEARCH_TIMEOUT = 15.0
QUERY_CACHE_TTL = 3600.0
QUERY_CACHE_SIZE = 2000
Kind = Literal["query", "document"]
Sleep = Callable[[float], Awaitable[None]]


class MLError(Exception):
    pass


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None
    model: str | None = None


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class MLClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 120.0,
        max_retries: int = 3,
        batch_size: int = 64,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.batch_size = batch_size
        self._transport = transport
        self._sleep = sleep
        self._http: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queries: dict[str, tuple[float, list[float]]] = {}

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._http is None or self._http.is_closed or self._loop is not loop:
            self._http = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout, transport=self._transport
            )
            self._loop = loop
        return self._http

    async def _post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        *,
        fast: bool = False,
    ) -> dict[str, Any]:
        http = self._client()
        retries = min(self.max_retries, 1) if fast else self.max_retries
        timeout = min(self.timeout, SEARCH_TIMEOUT) if fast else self.timeout
        for attempt in range(retries + 1):
            try:
                response = await http.post(path, json=payload, files=files, timeout=timeout)
                response.raise_for_status()
                body: dict[str, Any] = response.json()
                return body
            except httpx.HTTPError as exc:
                if not _retryable(exc) or attempt == retries:
                    raise MLError(f"{path}: {exc!r}") from exc
                delay = min(10.0, 0.5 * 2**attempt) * (0.5 + random.random() / 2)  # noqa: S311
                log.info("ml.retry", path=path, attempt=attempt, delay=round(delay, 2))
                await self._sleep(delay)
        raise AssertionError("unreachable")

    def _cached(self, text: str) -> list[float] | None:
        hit = self._queries.get(text)
        if hit is None or hit[0] < time.monotonic():
            return None
        return hit[1]

    def _remember(self, text: str, vector: list[float]) -> None:
        if len(self._queries) >= QUERY_CACHE_SIZE:
            self._queries.pop(next(iter(self._queries)))
        self._queries[text] = (time.monotonic() + QUERY_CACHE_TTL, vector)

    async def embed(self, texts: list[str], kind: Kind) -> list[list[float]]:
        query = kind == "query" and len(texts) == 1
        if query and (cached := self._cached(texts[0])) is not None:
            return [cached]
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            body = await self._post("/embed", {"texts": batch, "kind": kind}, fast=query)
            got = body.get("embeddings", [])
            if len(got) != len(batch) or any(len(v) != EMBEDDING_DIM for v in got):
                raise MLError(
                    f"/embed: ожидалось {len(batch)} векторов размерности {EMBEDDING_DIM}"
                )
            vectors.extend(got)
        if query:
            self._remember(texts[0], vectors[0])
        return vectors

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        body = await self._post("/rerank", {"query": query, "documents": documents}, fast=True)
        scores: list[float] = body.get("scores", [])
        if len(scores) != len(documents):
            raise MLError("/rerank: число оценок не совпадает с числом документов")
        return scores

    async def transcribe(self, audio: bytes, mime_type: str | None = None) -> Transcript:
        content_type = (mime_type or "application/octet-stream").split(";")[0].strip()
        body = await self._post("/transcribe", files={"file": ("audio", audio, content_type)})
        return Transcript(
            text=str(body.get("text", "")),
            language=body.get("language"),
            language_probability=body.get("language_probability"),
            duration=body.get("duration"),
            model=body.get("model"),
        )


@lru_cache
def get_ml_client() -> MLClient:
    settings = get_settings()
    return MLClient(
        settings.ml_url, timeout=settings.ml_timeout, max_retries=settings.ml_max_retries
    )
