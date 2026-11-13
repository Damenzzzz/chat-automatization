import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.base import Context, Deps, Outcome, Service
from app.automations.registry import SERVICES
from app.db.session import get_sessionmaker, tenant_session
from app.models import Automation, AutomationRun

log = structlog.get_logger()

LOCK_SECONDS = 120


class BusyError(Exception):
    pass


def read_settings(service: Service[Any], row: Automation | None) -> BaseModel:
    model: type[BaseModel] = service.settings_model
    try:
        return model.model_validate(row.settings if row else {})
    except ValidationError:
        return model()


def is_enabled(service: Service[Any], row: Automation | None) -> bool:
    return row.enabled if row else service.default_enabled


async def load(session: AsyncSession, kind: str) -> Automation | None:
    return await session.scalar(select(Automation).where(Automation.kind == kind))


async def ensure_row(
    session: AsyncSession, tenant_id: uuid.UUID, service: Service[Any]
) -> Automation:
    row = await load(session, service.kind)
    if row is None:
        row = Automation(
            tenant_id=tenant_id,
            kind=service.kind,
            enabled=service.default_enabled,
            settings=service.settings_model().model_dump(mode="json"),
            state={},
        )
        session.add(row)
        await session.flush()
    return row


async def _record_failure(tenant_id: uuid.UUID, kind: str, trigger: str) -> AutomationRun:
    async with tenant_session(tenant_id) as session:
        run = AutomationRun(
            tenant_id=tenant_id,
            kind=kind,
            trigger=trigger,
            status="failed",
            summary="Запуск не удался. Мы уже знаем об ошибке — попробуйте позже.",
            details={},
        )
        session.add(run)
        await session.flush()
        await session.refresh(run)
        session.expunge(run)
        return run


async def execute(
    tenant_id: uuid.UUID, kind: str, trigger: str, deps: Deps, now: datetime | None = None
) -> AutomationRun | None:
    """Один запуск сервиса. По расписанию пустой запуск в историю не пишется."""
    service = SERVICES[kind]
    moment = now or datetime.now(UTC)
    lock = f"automation:{tenant_id}:{kind}"
    if not await deps.redis.set(lock, "1", nx=True, ex=LOCK_SECONDS):
        if trigger == "manual":
            raise BusyError
        return None
    try:
        async with tenant_session(tenant_id) as session:
            row = await load(session, kind)
            settings = read_settings(service, row)
            if trigger == "schedule":
                if not is_enabled(service, row):
                    return None
                state = dict(row.state) if row else {}
                if not service.due(settings, state, row.last_run_at if row else None, moment):
                    return None
            row = row or await ensure_row(session, tenant_id, service)
            ctx = Context(session, tenant_id, moment, dict(row.state), deps, trigger)
            outcome: Outcome = await service.run(ctx, settings)
            row.state = ctx.state
            row.last_run_at = moment
            if outcome.status == "empty" and trigger == "schedule":
                return None
            run = AutomationRun(
                tenant_id=tenant_id,
                kind=kind,
                trigger=trigger,
                status=outcome.status,
                summary=outcome.summary,
                details=outcome.details,
            )
            session.add(run)
            await session.flush()
            await session.refresh(run)
            session.expunge(run)
            return run
    except Exception:
        log.exception("automation.failed", tenant_id=str(tenant_id), kind=kind, trigger=trigger)
        return await _record_failure(tenant_id, kind, trigger)
    finally:
        await deps.redis.delete(lock)


async def due_automations() -> list[tuple[uuid.UUID, str]]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(text("SELECT * FROM due_automations()"))
        return [(row.tenant_id, row.kind) for row in rows if row.kind in SERVICES]


async def run_due(deps: Deps) -> int:
    done = 0
    for tenant_id, kind in await due_automations():
        if await execute(tenant_id, kind, "schedule", deps) is not None:
            done += 1
    return done


async def purge_runs(keep_days: int) -> int:
    async with get_sessionmaker()() as session, session.begin():
        removed = await session.scalar(
            text("SELECT purge_automation_runs(:days)"), {"days": keep_days}
        )
    return int(removed or 0)
