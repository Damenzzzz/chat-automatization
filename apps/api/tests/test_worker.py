from app.worker import WorkerSettings, ping


async def test_ping_task() -> None:
    assert await ping({}) == "pong"


def test_worker_registers_functions() -> None:
    assert ping in WorkerSettings.functions
