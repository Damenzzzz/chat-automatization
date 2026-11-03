import uuid
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.catalog.ingest import run_ingest
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.storage import get_storage

_settings = get_settings()
configure_logging(_settings.log_level, json=_settings.env == "prod")


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


async def ingest_catalog(ctx: dict[str, Any], tenant_id: str, job_id: str) -> dict[str, int]:
    stats = await run_ingest(uuid.UUID(tenant_id), uuid.UUID(job_id), get_storage())
    return vars(stats)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, ingest_catalog]
    job_timeout = 1800
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
