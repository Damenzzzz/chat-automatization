"""ARQ-воркер. Запуск: arq app.worker.WorkerSettings"""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging

_settings = get_settings()
configure_logging(_settings.log_level, json=_settings.env == "prod")


async def ping(ctx: dict[str, Any]) -> str:
    """Служебная задача: проверка, что воркер жив. ARQ требует хотя бы одну функцию."""
    return "pong"


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
