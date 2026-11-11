import uuid
from typing import Any, ClassVar

import structlog
from arq import Retry, cron, func
from arq.connections import RedisSettings

from app.agent.checkpoint import close_checkpointer, get_checkpointer
from app.agent.nodes import AgentDeps
from app.agent.runtime import Agent
from app.billing.alerts import NOTIFY_OWNER, send_owner_message
from app.catalog.ingest import run_ingest
from app.catalog.reindex import reindex_tenant, tenants_needing_reindex
from app.channels.gateway import FLUSH, seq_key
from app.channels.idle import (
    purge_search_log,
    release_idle_conversations,
    retire_idle_conversations,
    stale_new_leads,
)
from app.channels.outbound import Outbound
from app.channels.processor import Processor
from app.channels.registry import get_adapters
from app.channels.staff import notify_staff
from app.channels.store import load_channel
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
STALE_BUFFER_SECONDS = 90


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
    sent = await notify_staff(get_redis(), uuid.UUID(tenant_id), event, payload, get_adapters())
    log.info("manager.notify", tenant_id=tenant_id, notification=event, sent=sent, **payload)


async def release_idle(ctx: dict[str, Any]) -> int:
    hours = _settings.human_idle_release_hours
    if hours <= 0:
        return 0
    released = await release_idle_conversations(hours)
    if released:
        log.info("conversations.released", count=released)
    return released


async def notify_owner(ctx: dict[str, Any], tenant_id: str, text: str) -> int:
    return await send_owner_message(uuid.UUID(tenant_id), text, get_adapters())


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


async def housekeeping(ctx: dict[str, Any]) -> dict[str, int]:
    retired = await retire_idle_conversations(
        _settings.conversation_idle_close_days, _settings.sandbox_keep_days
    )
    checkpointer = await get_checkpointer()
    for conversation_id in retired:
        await checkpointer.adelete_thread(str(conversation_id))
    purged = await purge_search_log(_settings.search_log_keep_days)
    log.info("housekeeping.done", retired=len(retired), search_log=purged)
    return {"retired": len(retired), "search_log": purged}


async def remind_leads(ctx: dict[str, Any]) -> int:
    hours = _settings.lead_reminder_hours
    if hours <= 0:
        return 0
    redis, sent = get_redis(), 0
    for tenant_id, lead_id, total in await stale_new_leads(hours):
        if not await redis.set(f"lead-reminded:{lead_id}", "1", nx=True, ex=7 * 24 * 3600):
            continue
        payload = {"lead_id": str(lead_id), "total_kzt": total, "hours": hours}
        sent += await notify_staff(redis, tenant_id, "lead.stale", payload, get_adapters())
    return sent


async def sweep_inbox(ctx: dict[str, Any], stale_seconds: int = STALE_BUFFER_SECONDS) -> int:
    redis, queue, swept = get_redis(), get_queue(), 0
    async for name in redis.scan_iter(match="inbox:*", count=200):
        if await redis.object("IDLETIME", name) < stale_seconds:
            continue
        _, channel_id, key = name.split(":", 2)
        channel = await load_channel(uuid.UUID(channel_id))
        if channel is None:
            await redis.delete(name)
            continue
        seq = int(await redis.get(seq_key(channel_id, key)) or 0)
        await queue.enqueue(FLUSH, str(channel.tenant_id), channel_id, key, seq)
        swept += 1
    if swept:
        log.warning("channel.inbox_swept", count=swept)
    return swept


class WorkerSettings:
    on_startup = startup
    on_shutdown = shutdown
    functions: ClassVar[list[Any]] = [
        ping,
        ingest_catalog,
        notify_manager,
        func(notify_owner, name=NOTIFY_OWNER),
        func(flush_customer, name=FLUSH, keep_result=0, max_tries=FLUSH_MAX_TRIES),
        func(reindex_embeddings, name=REINDEX, keep_result=0),
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(reindex_all, minute=set(range(0, 60, 10)), run_at_startup=True),
        cron(release_idle, minute=set(range(5, 60, 10))),
        cron(sweep_inbox, minute=set(range(1, 60, 2))),
        cron(remind_leads, minute={7, 37}),
        cron(housekeeping, hour={22}, minute={30}),
    ]
    job_timeout = 1800
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
