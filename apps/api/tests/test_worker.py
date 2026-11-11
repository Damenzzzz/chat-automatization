import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import worker
from app.channels.idle import release_idle_conversations, retire_idle_conversations
from app.worker import WorkerSettings, notify_manager, ping
from tests.agent_helpers import make_conversation
from tests.channel_helpers import make_channel
from tests.conftest import RecordingQueue


async def test_ping_task() -> None:
    assert await ping({}) == "pong"


def test_worker_registers_functions() -> None:
    assert ping in WorkerSettings.functions


async def test_notify_manager_runs_with_real_logger(database: None, redis: Redis) -> None:
    payload = {"conversation_id": "c", "channel": "telegram"}
    await notify_manager({}, str(uuid.uuid4()), "customer_message", payload)


async def test_idle_human_dialog_returns_to_bot(owner_engine: AsyncEngine) -> None:
    tenant_id, idle = await make_conversation(owner_engine, mode="human")
    _, fresh = await make_conversation(owner_engine, tenant_id, mode="human")
    async with owner_engine.begin() as conn:
        for conversation_id, minutes in ((idle, 13 * 60), (fresh, 1)):
            await conn.execute(
                text(
                    "UPDATE conversations SET last_message_at = now() - make_interval(mins => :m)"
                    " WHERE id = :c"
                ),
                {"c": conversation_id, "m": minutes},
            )

    assert await release_idle_conversations(12) == 1

    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT id, mode FROM conversations WHERE tenant_id = :t"), {"t": tenant_id}
        )
        modes = {row.id: row.mode for row in rows}
    assert modes == {idle: "bot", fresh: "human"}


async def test_housekeeping_closes_old_dialogs_and_drops_sandbox(owner_engine: AsyncEngine) -> None:
    tenant_id, old = await make_conversation(owner_engine)
    _, fresh = await make_conversation(owner_engine, tenant_id)
    _, sandbox = await make_conversation(owner_engine, tenant_id)
    async with owner_engine.begin() as conn:
        for conversation_id, days in ((old, 31), (fresh, 1), (sandbox, 8)):
            await conn.execute(
                text(
                    "UPDATE conversations SET sandbox = :s,"
                    " last_message_at = now() - make_interval(days => :d) WHERE id = :c"
                ),
                {"c": conversation_id, "d": days, "s": conversation_id == sandbox},
            )

    retired = await retire_idle_conversations(30, 7)

    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT id, status FROM conversations WHERE tenant_id = :t"), {"t": tenant_id}
        )
        statuses = {row.id: row.status for row in rows}
    assert set(retired) == {old, sandbox}
    assert statuses == {old: "closed", fresh: "open"}


async def test_stale_lead_is_reminded_once(
    owner_engine: AsyncEngine, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO leads (tenant_id, conversation_id, total_kzt, created_at)"
                " VALUES (:t, :c, 52000, now() - interval '3 hours')"
            ),
            {"t": tenant_id, "c": conversation_id},
        )
    sent: list[str] = []

    async def fake_notify(*args: object) -> int:
        sent.append(str(args[2]))
        return 1

    monkeypatch.setattr(worker, "notify_staff", fake_notify)

    assert await worker.remind_leads({}) == 1
    assert await worker.remind_leads({}) == 0
    assert sent == ["lead.stale"]


async def test_sweeper_requeues_stranded_buffer(
    owner_engine: AsyncEngine, redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, _ = await make_conversation(owner_engine)
    channel_id = await make_channel(owner_engine, tenant_id)
    queue = RecordingQueue()
    monkeypatch.setattr(worker, "get_queue", lambda: queue)
    pipe = redis.pipeline()
    pipe.rpush(f"inbox:{channel_id}:abc", "{}")
    pipe.set(f"inbox-seq:{channel_id}:abc", 4)
    await pipe.execute()

    assert await worker.sweep_inbox({}, stale_seconds=10_000) == 0
    assert await worker.sweep_inbox({}, stale_seconds=0) == 1
    assert queue.jobs[-1] == ("flush_customer", (str(tenant_id), str(channel_id), "abc", 4))
