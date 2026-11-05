import uuid
from typing import Any, ClassVar

import structlog
from arq import Retry, cron, func
from arq.connections import RedisSettings

from app.agent.checkpoint import close_checkpointer, get_checkpointer
from app.agent.nodes import AgentDeps
from app.agent.runtime import Agent
from app.catalog.ingest import run_ingest
from app.catalog.reindex import reindex_tenant, tenants_needing_reindex
from app.channels.gateway import FLUSH
from app.channels.outbound import Outbound
from app.channels.processor import Processor
from app.channels.registry import get_adapters
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.queue import get_queue
from app.core.redis import get_redis
from app.core.storage import get_storage
from app.llm import get_llm
from app.mlclient import get_ml_client

_settings = get_settings()
configure_logging(_settings.log_level, json=_settings.env == "prod")
log = structlog.get_logger()

REINDEX = "reindex_embeddings"
FLUSH_MAX_TRIES = 3


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
    log.info("manager.notify", tenant_id=tenant_id, notification=event, **payload)


async def flush_customer(
    ctx: dict[str, Any], tenant_id: str, channel_id: str, key: str, seq: int
) -> str:
    processor: Processor = ctx["processor"]
    try:
        return await processor.flush(tenant_id, channel_id, key, seq)
    except Exception as exc:
        attempt = ctx.get("job_try", 1)
        log.exception("channel.flush_failed", channel_id=channel_id, attempt=attempt)
        if attempt < FLUSH_MAX_TRIES:
            raise Retry(defer=attempt * 5) from exc
        await processor.give_up(channel_id, key)
        return "failed"


async def startup(ctx: dict[str, Any]) -> None:
    queue = get_queue()
    outbound = Outbound(get_adapters())
    deps = AgentDeps(llm=get_llm(), ml=get_ml_client(), queue=queue, channels=outbound)
    agent = Agent(deps, await get_checkpointer())
    ctx["processor"] = Processor(get_redis(), queue, agent, outbound)


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_checkpointer()


class WorkerSettings:
    on_startup = startup
    on_shutdown = shutdown
    functions: ClassVar[list[Any]] = [
        ping,
        ingest_catalog,
        notify_manager,
        func(flush_customer, name=FLUSH, keep_result=0, max_tries=FLUSH_MAX_TRIES),
        func(reindex_embeddings, name=REINDEX, keep_result=0),
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(reindex_all, minute=set(range(0, 60, 10)), run_at_startup=True)
    ]
    job_timeout = 1800
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
