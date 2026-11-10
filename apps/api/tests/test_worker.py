import uuid

from redis.asyncio import Redis

from app.worker import WorkerSettings, notify_manager, ping


async def test_ping_task() -> None:
    assert await ping({}) == "pong"


def test_worker_registers_functions() -> None:
    assert ping in WorkerSettings.functions


async def test_notify_manager_runs_with_real_logger(database: None, redis: Redis) -> None:
    payload = {"conversation_id": "c", "channel": "telegram"}
    await notify_manager({}, str(uuid.uuid4()), "customer_message", payload)
