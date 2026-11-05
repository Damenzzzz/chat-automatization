from app.worker import WorkerSettings, notify_manager, ping


async def test_ping_task() -> None:
    assert await ping({}) == "pong"


def test_worker_registers_functions() -> None:
    assert ping in WorkerSettings.functions


async def test_notify_manager_runs_with_real_logger() -> None:
    await notify_manager(
        {}, "tenant", "customer_message", {"conversation_id": "c", "channel": "telegram"}
    )
