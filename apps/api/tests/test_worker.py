import uuid
from datetime import timedelta

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channels.idle import release_idle_conversations
from app.worker import WorkerSettings, notify_manager, ping
from tests.agent_helpers import make_conversation


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
        for conversation_id, age in ((idle, timedelta(hours=13)), (fresh, timedelta(minutes=1))):
            await conn.execute(
                text("UPDATE conversations SET last_message_at = now() - :age WHERE id = :c"),
                {"c": conversation_id, "age": age},
            )

    assert await release_idle_conversations(12) == 1

    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT id, mode FROM conversations WHERE tenant_id = :t"), {"t": tenant_id}
        )
        modes = {row.id: row.mode for row in rows}
    assert modes == {idle: "bot", fresh: "human"}
