import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.channels.gateway import FLUSH, Gateway, buffer_key, customer_key
from app.channels.outbound import Outbound
from app.channels.processor import Processor, open_conversation
from app.channels.store import load_channel
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent
from tests.channel_helpers import RecordingAdapter, incoming, make_channel
from tests.conftest import RecordingQueue
from tests.fake_ml import make_shop

CATALOG = [{"sku": "PN-1", "name": "Белые пионы", "price": 52000, "stock": 3}]
UNDERSTOOD = Understanding(lang="ru", intent="smalltalk", complexity="low")


@pytest.fixture
async def shop(owner_engine: AsyncEngine, redis: Any) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await make_shop(owner_engine, CATALOG)
    return tenant_id, await make_channel(owner_engine, tenant_id)


async def _gateway(channel_id: uuid.UUID, redis: Any) -> tuple[Gateway, RecordingQueue, Any]:
    queue = RecordingQueue()
    channel = await load_channel(channel_id)
    assert channel is not None
    return Gateway(redis, queue), queue, channel


async def _processor(
    redis: Any, *, llm: Any = None, adapter: RecordingAdapter | None = None
) -> tuple[Processor, RecordingAdapter, RecordingQueue]:
    adapter = adapter or RecordingAdapter()
    outbound = Outbound({"telegram": adapter})
    agent, queue = await make_agent(llm=llm, channels=outbound)
    return Processor(redis, queue, agent, outbound), adapter, queue


def _flush_args(queue: RecordingQueue, index: int = -1) -> tuple[str, str, str, int]:
    name, args = queue.jobs[index]
    assert name == FLUSH
    tenant_id, channel_id, key, seq = args
    assert isinstance(seq, int)
    return str(tenant_id), str(channel_id), str(key), seq


async def _rows(engine: AsyncEngine, tenant_id: uuid.UUID) -> list[tuple[str, str | None]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT role, content FROM messages WHERE tenant_id = :t ORDER BY created_at"),
            {"t": tenant_id},
        )
        return [(r.role, r.content) for r in rows]


async def test_duplicate_external_id_is_dropped(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any
) -> None:
    _, channel_id = shop
    gateway, queue, channel = await _gateway(channel_id, redis)

    assert await gateway.accept(channel, incoming(channel_id, "m1")) is True
    assert await gateway.accept(channel, incoming(channel_id, "m1")) is False
    assert await gateway.accept(channel, incoming(channel_id, "m2")) is True

    assert len(queue.jobs) == 2
    assert queue.delays == [1.5, 1.5]
    assert await redis.llen(buffer_key(channel_id, customer_key("c1"))) == 2
    assert 0 < await redis.ttl(f"dedup:{channel_id}:m1") <= 24 * 3600


async def test_failed_enqueue_releases_dedup_so_platform_can_retry(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any
) -> None:
    _, channel_id = shop
    _, queue, channel = await _gateway(channel_id, redis)

    class Broken(RecordingQueue):
        async def enqueue(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("redis")

    with pytest.raises(ConnectionError):
        await Gateway(redis, Broken()).accept(channel, incoming(channel_id, "m1"))
    assert await Gateway(redis, queue).accept(channel, incoming(channel_id, "m1")) is True


async def test_job_args_do_not_expose_customer_id(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any
) -> None:
    _, channel_id = shop
    gateway, queue, channel = await _gateway(channel_id, redis)
    await gateway.accept(channel, incoming(channel_id, "m1", customer="77011234567"))
    assert "77011234567" not in str(queue.jobs)


async def test_messages_within_window_are_merged_into_one_turn(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any, owner_engine: AsyncEngine
) -> None:
    tenant_id, channel_id = shop
    gateway, queue, channel = await _gateway(channel_id, redis)
    for external_id, body in (("m1", "есть пионы?"), ("m2", "белые"), ("m3", "на завтра")):
        await gateway.accept(channel, incoming(channel_id, external_id, body))
    llm = FakeLLM([UNDERSTOOD, "Да, есть."])
    processor, adapter, _ = await _processor(redis, llm=llm)

    assert await processor.flush(*_flush_args(queue, 0)) == "superseded"
    assert await processor.flush(*_flush_args(queue, 1)) == "superseded"
    assert llm.calls == []
    assert await processor.flush(*_flush_args(queue, 2)) == "done"

    assert await _rows(owner_engine, tenant_id) == [
        ("customer", "есть пионы?\nбелые\nна завтра"),
        ("bot", "Да, есть."),
    ]
    assert len(llm.calls) == 2
    assert adapter.acked == ["m1", "m2", "m3"]
    assert [c for c, _ in adapter.sent] == ["c1"]
    assert adapter.sent[0][1].text == "Да, есть."
    assert await redis.llen(buffer_key(channel_id, customer_key("c1"))) == 0


async def test_different_customers_are_not_merged(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any
) -> None:
    _, channel_id = shop
    gateway, queue, channel = await _gateway(channel_id, redis)
    await gateway.accept(channel, incoming(channel_id, "m1", "раз", customer="a"))
    await gateway.accept(channel, incoming(channel_id, "m2", "два", customer="b"))
    processor, adapter, _ = await _processor(redis)

    assert await processor.flush(*_flush_args(queue, 0)) == "done"
    assert await processor.flush(*_flush_args(queue, 1)) == "done"
    assert sorted(c for c, _ in adapter.sent) == ["a", "b"]


async def test_busy_conversation_requeues_and_keeps_buffer(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any
) -> None:
    _, channel_id = shop
    gateway, queue, channel = await _gateway(channel_id, redis)
    await gateway.accept(channel, incoming(channel_id, "m1", "жду"))
    conversation_id = await open_conversation(channel, incoming(channel_id, "x"))
    processor, adapter, retry_queue = await _processor(redis)
    processor.queue = retry_queue

    lock = redis.lock(f"lock:conversation:{conversation_id}", timeout=30)
    await lock.acquire()
    assert await processor.flush(*_flush_args(queue)) == "busy"
    assert retry_queue.jobs[-1][0] == FLUSH
    assert retry_queue.delays[-1] == 1.0
    assert await redis.llen(buffer_key(channel_id, customer_key("c1"))) == 1
    assert adapter.sent == []
    await lock.release()

    assert await processor.flush(*_flush_args(queue)) == "done"
    assert len(adapter.sent) == 1


async def test_human_mode_saves_and_notifies_without_reply(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any, owner_engine: AsyncEngine
) -> None:
    tenant_id, channel_id = shop
    gateway, queue, channel = await _gateway(channel_id, redis)
    conversation_id = await open_conversation(channel, incoming(channel_id, "x"))
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE conversations SET mode = 'human' WHERE id = :c"), {"c": conversation_id}
        )
    await gateway.accept(channel, incoming(channel_id, "m1", "где менеджер?"))
    llm = FakeLLM([])
    processor, adapter, _ = await _processor(redis, llm=llm)
    notify_queue = RecordingQueue()
    processor.queue = notify_queue

    assert await processor.flush(*_flush_args(queue)) == "done"

    assert await _rows(owner_engine, tenant_id) == [("customer", "где менеджер?")]
    assert llm.calls == []
    assert adapter.sent == []
    assert notify_queue.jobs == [
        (
            "notify_manager",
            (
                str(tenant_id),
                "customer_message",
                {"conversation_id": str(conversation_id), "channel": "telegram"},
            ),
        )
    ]


async def test_failed_turn_keeps_buffer_for_retry_and_give_up_clears_it(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any
) -> None:
    _, channel_id = shop
    gateway, queue, channel = await _gateway(channel_id, redis)
    await gateway.accept(channel, incoming(channel_id, "m1"))
    processor, _, _ = await _processor(redis)

    async def boom(**kwargs: Any) -> None:
        raise RuntimeError("упало")

    processor.agent.run = boom  # type: ignore[method-assign,assignment]
    notify_queue = RecordingQueue()
    processor.queue = notify_queue
    tenant_id, channel_arg, key, seq = _flush_args(queue)

    with pytest.raises(RuntimeError):
        await processor.flush(tenant_id, channel_arg, key, seq)
    buffer = buffer_key(channel_id, key)
    assert await redis.llen(buffer) == 1
    with pytest.raises(RuntimeError):
        await processor.flush(tenant_id, channel_arg, key, seq)

    await processor.give_up(channel_arg, key)
    assert await redis.llen(buffer) == 0
    assert notify_queue.jobs[-1][1][1] == "turn_failed"


async def test_concurrent_messages_share_one_conversation(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any
) -> None:
    _, channel_id = shop
    _, _, channel = await _gateway(channel_id, redis)
    ids = await asyncio.gather(
        *(open_conversation(channel, incoming(channel_id, f"m{i}")) for i in range(5))
    )
    assert len(set(ids)) == 1


async def test_disabled_channel_drops_buffer(owner_engine: AsyncEngine, redis: Any) -> None:
    tenant_id = await make_shop(owner_engine, CATALOG)
    channel_id = await make_channel(owner_engine, tenant_id, status="disabled")
    gateway, queue, channel = await _gateway(channel_id, redis)
    await gateway.accept(channel, incoming(channel_id, "m1"))
    processor, adapter, _ = await _processor(redis)

    assert await processor.flush(*_flush_args(queue)) == "skipped"
    assert adapter.sent == []
    assert await redis.llen(buffer_key(channel_id, customer_key("c1"))) == 0


async def test_reply_sends_cards_with_price_from_database(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any, owner_engine: AsyncEngine
) -> None:
    tenant_id, channel_id = shop
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE products SET images = :i WHERE tenant_id = :t"),
            {"i": ["https://shop.kz/p.jpg"], "t": tenant_id},
        )
    gateway, queue, channel = await _gateway(channel_id, redis)
    await gateway.accept(channel, incoming(channel_id, "m1", "пионы?"))
    llm = FakeLLM(
        [Understanding(lang="ru", intent="product", complexity="low"), "Есть белые пионы."]
    )
    processor, adapter, _ = await _processor(redis, llm=llm)

    assert await processor.flush(*_flush_args(queue)) == "done"

    card = adapter.sent[0][1].cards[0]
    assert card.caption == "Белые пионы\n52 000 ₸"
    assert card.image_url == "https://shop.kz/p.jpg"
    assert card.buttons[0].payload == "order:ru:PN-1"


async def test_delivery_failure_keeps_reply_and_records_trace(
    shop: tuple[uuid.UUID, uuid.UUID], redis: Any, owner_engine: AsyncEngine
) -> None:
    tenant_id, channel_id = shop
    gateway, queue, channel = await _gateway(channel_id, redis)
    await gateway.accept(channel, incoming(channel_id, "m1", "привет"))
    llm = FakeLLM([UNDERSTOOD, "Здравствуйте!"])
    processor, _, _ = await _processor(redis, llm=llm, adapter=RecordingAdapter(fail=True))

    assert await processor.flush(*_flush_args(queue)) == "done"

    async with owner_engine.connect() as conn:
        steps = await conn.scalar(
            text("SELECT trace->'steps' FROM messages WHERE tenant_id = :t AND role = 'bot'"),
            {"t": tenant_id},
        )
    sent = next(s for s in steps if s["node"] == "send")
    assert sent["delivered"] is False
    assert sent["error"] == "сеть недоступна"


async def test_sandbox_never_delivers(owner_engine: AsyncEngine, redis: Any) -> None:
    from tests.agent_helpers import make_conversation

    adapter = RecordingAdapter()
    agent, _ = await make_agent(channels=Outbound({"telegram": adapter}))
    tenant_id, conversation_id = await make_conversation(owner_engine)
    turn = await agent.run(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text="привет",
        sandbox=True,
        channel_id=uuid.uuid4(),
        customer_external_id="c1",
    )
    assert adapter.sent == []
    assert next(s for s in turn.trace if s["node"] == "send")["delivered"] is False


def test_httpx_does_not_log_urls_with_tokens() -> None:
    import logging

    from app.core.logging import configure_logging

    configure_logging("DEBUG")
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
