import json
from collections.abc import Callable

import httpx
import pytest

from app.mlclient import MLClient, MLError

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler, **kwargs: int) -> tuple[MLClient, list[float]]:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = MLClient(
        "http://ml:8001", transport=httpx.MockTransport(handler), sleep=sleep, **kwargs
    )
    return client, sleeps


def _embed_ok(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["texts"]
    return httpx.Response(200, json={"embeddings": [[0.1] * 1024 for _ in texts], "dim": 1024})


async def test_embed_batches_by_64() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/embed" and body["kind"] == "document"
        sizes.append(len(body["texts"]))
        return _embed_ok(request)

    client, _ = _client(handler)
    vectors = await client.embed([f"товар {i}" for i in range(150)], "document")

    assert sizes == [64, 64, 22]
    assert len(vectors) == 150 and len(vectors[0]) == 1024


async def test_retries_while_models_load() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, json={"detail": "models_loading"})
        return _embed_ok(request)

    client, sleeps = _client(handler)
    assert len(await client.embed(["пион"], "query")) == 1
    assert len(calls) == 3 and len(sleeps) == 2


async def test_client_error_is_not_retried() -> None:
    client, sleeps = _client(lambda r: httpx.Response(413, json={"detail": "too_many_texts"}))
    with pytest.raises(MLError):
        await client.embed(["x"], "document")
    assert sleeps == []


async def test_gives_up_on_network_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client, sleeps = _client(handler, max_retries=2)
    with pytest.raises(MLError):
        await client.embed(["x"], "document")
    assert len(sleeps) == 2


async def test_wrong_dimension_is_rejected() -> None:
    client, _ = _client(lambda r: httpx.Response(200, json={"embeddings": [[0.1] * 768]}))
    with pytest.raises(MLError, match="1024"):
        await client.embed(["x"], "document")


async def test_rerank() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json={"scores": [0.9, 0.1][: len(body["documents"])]})

    client, _ = _client(handler)
    assert await client.rerank("пионы", ["Пионы", "Колодки"]) == [0.9, 0.1]
    assert await client.rerank("пионы", []) == []
