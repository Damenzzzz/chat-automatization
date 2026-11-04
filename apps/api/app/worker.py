import uuid
from typing import Any, ClassVar

import structlog
from arq import cron, func
from arq.connections import RedisSettings

from app.catalog.ingest import run_ingest
from app.catalog.reindex import reindex_tenant, tenants_needing_reindex
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.storage import get_storage
from app.mlclient import get_ml_client

_settings = get_settings()
configure_logging(_settings.log_level, json=_settings.env == "prod")
log = structlog.get_logger()

REINDEX = "reindex_embeddings"


async def enqueue_reindex(redis: Any, tenant_id: uuid.UUID | str) -> None:
    await redis.enqueue_job(REINDEX, str(tenant_id), _job_id=f"reindex:{tenant_id}")


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


async def ingest_catalog(ctx: dict[str, Any], tenant_id: str, job_id: str) -> dict[str, int]:
    stats = await run_ingest(uuid.UUID(tenant_id), uuid.UUID(job_id), get_storage())
    if stats.created or stats.updated:
        await enqueue_reindex(ctx["redis"], tenant_id)
    return vars(stats)


async def reindex_embeddings(ctx: dict[str, Any], tenant_id: str) -> dict[str, int]:
    stats = await reindex_tenant(uuid.UUID(tenant_id), get_ml_client())
    return vars(stats)


async def reindex_all(ctx: dict[str, Any]) -> int:
    tenants = await tenants_needing_reindex()
    for tenant_id in tenants:
        await enqueue_reindex(ctx["redis"], tenant_id)
    return len(tenants)


async def notify_manager(
    ctx: dict[str, Any], tenant_id: str, event: str, payload: dict[str, Any]
) -> None:
    log.info("manager.notify", tenant_id=tenant_id, event=event, **payload)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        ingest_catalog,
        notify_manager,
        func(reindex_embeddings, name=REINDEX, keep_result=0),
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(reindex_all, minute=set(range(0, 60, 10)), run_at_startup=True)
    ]
    job_timeout = 1800
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
