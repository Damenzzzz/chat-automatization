import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.channels.gateway import FLUSH
from app.channels.outbound import Outbound
from app.channels.processor import Processor
from app.channels.types import OutgoingMessage, ProductCard
from app.channels.web import WebAdapter, customer_id, origin_allowed, stream_key
from app.llm.fake import FakeLLM
from app.routers import widget
from app.routers.channels import normalize_domain
from tests.agent_helpers import make_agent
from tests.channel_helpers import make_channel
from tests.conftest import RecordingQueue

ORIGIN = "https://pion.kz"
SESSION = "session-token-0123456789abcd"
HEADERS = {"Origin": ORIGIN, "X-Widget-Session": SESSION}


@pytest.fixture
async def key(owner_engine: AsyncEngine, client: AsyncClient) -> str:
    async with owner_engine.begin() as conn:
        tenant = await conn.scalar(text("INSERT INTO tenants (name) VALUES ('Т') RETURNING id"))
    value = uuid.uuid4().hex
    await make_channel(
        owner_engine,
        tenant,
        type_="web",
        secret=None,
        public_key=value,
        domain="pion.kz",
    )
    return value


async def _channel_id(engine: AsyncEngine, public_key: str) -> uuid.UUID:
    async with engine.connect() as conn:
        value: uuid.UUID = await conn.scalar(
            text("SELECT id FROM channels WHERE public_key = :k"), {"k": public_key}
        )
    return value


def _message(mid: str = "message-0001", body: str = "привет") -> dict[str, str]:
    return {"id": mid, "text": body}


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("https://pion.kz", True),
        ("https://www.pion.kz", True),
        ("http://pion.kz:8080", True),
        ("https://PION.kz", True),
        ("https://evil.kz", False),
        ("https://pion.kz.evil.com", False),
        ("https://notpion.kz", False),
        ("https://shop.pion.kz", False),
        ("null", False),
        ("", False),
        (None, False),
    ],
)
def test_origin_matching(origin: str | None, allowed: bool) -> None:
    assert origin_allowed("pion.kz", origin) is allowed


def test_origin_allows_bare_host_when_domain_has_www() -> None:
    assert origin_allowed("www.pion.kz", "https://pion.kz")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pion.kz", "pion.kz"),
        ("https://Pion.KZ/shop?x=1", "pion.kz"),
        ("  www.pion.kz ", "www.pion.kz"),
        ("localhost", "localhost"),
        ("пион.рф", "xn--h1akcc.xn--p1ai"),
        ("not a domain", None),
        ("javascript:alert(1)", None),
        ("", None),
        ("pion", None),
    ],
)
def test_normalize_domain(raw: str, expected: str | None) -> None:
    assert normalize_domain(raw) == expected


async def test_preflight_allows_only_shop_domain(client: AsyncClient, key: str) -> None:
    good = await client.options(f"/widget/{key}/messages", headers={"Origin": ORIGIN})
    assert good.status_code == 204
    assert good.headers["access-control-allow-origin"] == ORIGIN
    assert "X-Widget-Session" in good.headers["access-control-allow-headers"]

    bad = await client.options(f"/widget/{key}/messages", headers={"Origin": "https://evil.kz"})
    assert bad.status_code == 403
    assert "access-control-allow-origin" not in bad.headers


async def test_post_message_queues_and_returns_cors(
    client: AsyncClient, key: str, queue: RecordingQueue
) -> None:
    response = await client.post(f"/widget/{key}/messages", json=_message(), headers=HEADERS)
    assert response.status_code == 202
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert [name for name, _ in queue.jobs] == [FLUSH]


async def test_same_message_id_is_deduplicated(
    client: AsyncClient, key: str, queue: RecordingQueue
) -> None:
    url = f"/widget/{key}/messages"
    await client.post(url, json=_message(), headers=HEADERS)
    second = await client.post(url, json=_message(), headers=HEADERS)
    assert second.json() == {"accepted": False}
    assert len(queue.jobs) == 1


async def test_foreign_or_missing_origin_is_rejected(
    client: AsyncClient, key: str, queue: RecordingQueue
) -> None:
    url = f"/widget/{key}/messages"
    evil = await client.post(url, json=_message(), headers={**HEADERS, "Origin": "https://evil.kz"})
    assert evil.status_code == 403
    assert "access-control-allow-origin" not in evil.headers
    missing = await client.post(url, json=_message(), headers={"X-Widget-Session": SESSION})
    assert missing.status_code == 403
    assert queue.jobs == []


async def test_unknown_key_is_404(client: AsyncClient) -> None:
    response = await client.post("/widget/nope/messages", json=_message(), headers=HEADERS)
    assert response.status_code == 404


@pytest.mark.parametrize("session", [None, "short", "bad session with spaces 0123456789"])
async def test_invalid_session_is_rejected(
    client: AsyncClient, key: str, session: str | None
) -> None:
    headers = {"Origin": ORIGIN, **({"X-Widget-Session": session} if session else {})}
    response = await client.post(f"/widget/{key}/messages", json=_message(), headers=headers)
    assert response.status_code == 400
    assert response.headers["access-control-allow-origin"] == ORIGIN


@pytest.mark.parametrize(
    "body",
    [
        {"id": "message-0001", "text": "   "},
        {"id": "message-0001"},
        {"id": "x", "text": "привет"},
        {"id": "message-0001", "text": "я" * 2001},
        {"id": "message-0001", "payload": "evil:payload"},
    ],
)
async def test_bad_message_is_rejected(
    client: AsyncClient, key: str, queue: RecordingQueue, body: dict[str, str]
) -> None:
    response = await client.post(f"/widget/{key}/messages", json=body, headers=HEADERS)
    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert queue.jobs == []


async def test_session_rate_limit(client: AsyncClient, key: str) -> None:
    url = f"/widget/{key}/messages"
    codes = [
        (await client.post(url, json=_message(f"message-{i:04}"), headers=HEADERS)).status_code
        for i in range(widget.SESSION_PER_MINUTE + 1)
    ]
    assert codes[:-1] == [202] * widget.SESSION_PER_MINUTE
    assert codes[-1] == 429


async def test_ip_rate_limit_covers_rotating_sessions(
    client: AsyncClient, key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(widget, "IP_PER_MINUTE", 3)
    url = f"/widget/{key}/messages"
    codes = []
    for i in range(4):
        headers = {**HEADERS, "X-Widget-Session": f"rotating-session-{i:012}"}
        codes.append((await client.post(url, json=_message(), headers=headers)).status_code)
    assert codes == [202, 202, 202, 429]


async def test_stream_replays_after_last_event_id(
    client: AsyncClient, key: str, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(widget, "SSE_MAX_SECONDS", 0.2)
    monkeypatch.setattr(widget, "SSE_BLOCK_MS", 50)
    channel_id = await _channel_id(owner_engine, key)
    from app.channels.store import load_channel

    channel = await load_channel(channel_id)
    assert channel is not None
    adapter = WebAdapter()
    customer = customer_id(SESSION)
    await adapter.send(channel, customer, OutgoingMessage(text="первое"))
    await adapter.send(
        channel,
        customer,
        OutgoingMessage(text="второе", cards=[ProductCard(title="П", caption="П\n1 ₸")]),
    )

    full = await client.get(f"/widget/{key}/stream", headers=HEADERS)
    assert full.status_code == 200
    assert full.headers["content-type"].startswith("text/event-stream")
    assert full.headers["access-control-allow-origin"] == ORIGIN
    events = [e for e in full.text.split("\n\n") if e.startswith("id: ")]
    assert len(events) == 2
    first_id = events[0].splitlines()[0].removeprefix("id: ")
    data = json.loads(events[1].splitlines()[2].removeprefix("data: "))
    assert data["text"] == "второе"
    assert data["cards"][0]["caption"] == "П\n1 ₸"

    resumed = await client.get(
        f"/widget/{key}/stream", headers={**HEADERS, "Last-Event-ID": first_id}
    )
    assert "второе" in resumed.text
    assert "первое" not in resumed.text


async def test_stream_of_one_session_is_invisible_to_another(
    client: AsyncClient, key: str, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(widget, "SSE_MAX_SECONDS", 0.1)
    monkeypatch.setattr(widget, "SSE_BLOCK_MS", 30)
    from app.channels.store import load_channel

    channel = await load_channel(await _channel_id(owner_engine, key))
    assert channel is not None
    await WebAdapter().send(channel, customer_id(SESSION), OutgoingMessage(text="секрет"))
    other = {**HEADERS, "X-Widget-Session": "another-session-0123456789"}
    response = await client.get(f"/widget/{key}/stream", headers=other)
    assert "секрет" not in response.text


async def test_stream_requires_allowed_origin(client: AsyncClient, key: str) -> None:
    response = await client.get(
        f"/widget/{key}/stream", headers={**HEADERS, "Origin": "https://evil.kz"}
    )
    assert response.status_code == 403


async def test_reply_reaches_stream_end_to_end(
    client: AsyncClient,
    key: str,
    queue: RecordingQueue,
    redis: Any,
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(widget, "SSE_MAX_SECONDS", 0.2)
    monkeypatch.setattr(widget, "SSE_BLOCK_MS", 50)
    await client.post(f"/widget/{key}/messages", json=_message(), headers=HEADERS)
    llm = FakeLLM([Understanding(lang="ru", intent="smalltalk", complexity="low"), "Здравствуйте!"])
    outbound = Outbound({"web": WebAdapter()})
    agent, agent_queue = await make_agent(llm=llm, channels=outbound)
    processor = Processor(redis, agent_queue, agent, outbound)
    _, args = queue.jobs[-1]
    tenant_id, channel_id, customer_key_, seq = args
    assert isinstance(seq, int)

    assert await processor.flush(str(tenant_id), str(channel_id), str(customer_key_), seq) == "done"

    assert await redis.xlen(stream_key(channel_id, customer_id(SESSION))) == 1
    response = await client.get(f"/widget/{key}/stream", headers=HEADERS)
    assert "Здравствуйте!" in response.text


async def test_connect_web_returns_snippet_and_is_idempotent(
    client: AsyncClient, owner: uuid.UUID
) -> None:
    first = await client.post("/channels/web", json={"domain": "https://Pion.kz/shop"})
    assert first.status_code == 201
    body = first.json()
    assert body["domain"] == "pion.kz"
    assert body["status"] == "active"
    assert f'data-key="{body["public_key"]}"' in body["snippet"]
    assert 'data-api="https://api.test"' in body["snippet"]
    second = await client.post("/channels/web", json={"domain": "pion.kz"})
    assert second.json()["id"] == body["id"]
    assert second.json()["public_key"] == body["public_key"]


async def test_connect_web_rejects_bad_domain(client: AsyncClient, owner: uuid.UUID) -> None:
    response = await client.post("/channels/web", json={"domain": "javascript:alert(1)"})
    assert response.status_code == 400
