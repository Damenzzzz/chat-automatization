import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, StringConstraints, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import Agent, get_agent
from app.auth.deps import Principal, TenantDb, require_role
from app.automations.base import Context, Deps, Preview, Service
from app.automations.digest import DigestSettings
from app.automations.followup import FollowupSettings, deliver, reject_pending
from app.automations.lead_reminders import LeadReminderSettings
from app.automations.registry import SERVICES
from app.automations.runner import (
    BusyError,
    DisabledError,
    ensure_row,
    execute,
    is_enabled,
    load,
    read_settings,
)
from app.automations.stock import StockSettings
from app.channels.outbound import Outbound
from app.channels.registry import get_adapters
from app.core.net import client_ip
from app.core.ratelimit import limit
from app.core.redis import get_redis
from app.models import AutomationRun, Conversation, Customer, Followup, Tenant

router = APIRouter(tags=["automations"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
Owner = Annotated[Principal, Depends(require_role("owner"))]
Kind = Literal["digest", "stock", "followup", "lead_reminders"]
FollowupStatus = Literal["pending", "sent", "rejected", "expired", "failed"]
RUNS_PER_HOUR = 6
PREVIEWS_PER_HOUR = 120
SENDS_PER_HOUR = 120
FollowupText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)
]
SettingsOut = DigestSettings | StockSettings | FollowupSettings | LeadReminderSettings


class RunOut(BaseModel):
    id: uuid.UUID
    kind: str
    trigger: str
    status: str
    summary: str
    details: dict[str, Any]
    created_at: datetime


class AutomationOut(BaseModel):
    kind: Kind
    title: str
    description: str
    enabled: bool
    settings: SettingsOut
    last_run_at: datetime | None
    last_run: RunOut | None
    pending: int


class AutomationIn(BaseModel):
    enabled: bool | None = None
    settings: dict[str, Any] | None = None


class PreviewIn(BaseModel):
    settings: dict[str, Any] | None = None


class FollowupOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    customer_name: str | None
    channel: str | None
    text: str
    status: str
    created_at: datetime
    sent_at: datetime | None


class FollowupSendIn(BaseModel):
    text: FollowupText | None = None


def get_deps(agent: Annotated[Agent, Depends(get_agent)]) -> Deps:
    adapters = get_adapters()
    return Deps(get_redis(), adapters, Outbound(adapters), agent.remember_manager_reply)


def get_light_deps() -> Deps:
    adapters = get_adapters()
    return Deps(get_redis(), adapters, Outbound(adapters))


def run_out(run: AutomationRun) -> RunOut:
    return RunOut(
        id=run.id,
        kind=run.kind,
        trigger=run.trigger,
        status=run.status,
        summary=run.summary,
        details=run.details,
        created_at=run.created_at,
    )


def parse_settings(service: Service[Any], raw: dict[str, Any]) -> BaseModel:
    model: type[BaseModel] = service.settings_model
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "settings_invalid") from exc


async def automation_out(db: AsyncSession, service: Service[Any]) -> AutomationOut:
    row = await load(db, service.kind)
    last = await db.scalar(
        select(AutomationRun)
        .where(AutomationRun.kind == service.kind)
        .order_by(AutomationRun.created_at.desc())
        .limit(1)
    )
    pending = 0
    if service.kind == "followup":
        pending = int(
            await db.scalar(
                select(func.count()).select_from(Followup).where(Followup.status == "pending")
            )
            or 0
        )
    return AutomationOut(
        kind=service.kind,
        title=service.title,
        description=service.description,
        enabled=is_enabled(service, row),
        settings=read_settings(service, row),
        last_run_at=row.last_run_at if row else None,
        last_run=run_out(last) if last else None,
        pending=pending,
    )


@router.get("/automations")
async def list_automations(principal: Member, db: TenantDb) -> list[AutomationOut]:
    return [await automation_out(db, service) for service in SERVICES.values()]


@router.put("/automations/{kind}")
async def save_automation(
    kind: Kind, body: AutomationIn, principal: Owner, db: TenantDb
) -> AutomationOut:
    service = SERVICES[kind]
    row = await ensure_row(db, principal.tenant_id, service)
    if body.settings is not None:
        row.settings = parse_settings(service, body.settings).model_dump(mode="json")
    if body.enabled is not None:
        if row.enabled and not body.enabled and kind == "followup":
            await reject_pending(db)
        row.enabled = body.enabled
    await db.flush()
    return await automation_out(db, service)


@router.post("/automations/{kind}/preview")
async def preview_automation(
    kind: Kind,
    request: Request,
    principal: Member,
    db: TenantDb,
    deps: Annotated[Deps, Depends(get_light_deps)],
    body: PreviewIn | None = None,
) -> Preview:
    # В демо-магазине все посетители — один пользователь, поэтому считаем ещё и по адресу.
    key = f"rl:automation-preview:{principal.tenant_id}:{client_ip(request)}"
    await limit(deps.redis, key, PREVIEWS_PER_HOUR, 3600)
    service = SERVICES[kind]
    row = await load(db, kind)
    settings = (
        parse_settings(service, body.settings)
        if body and body.settings is not None
        else read_settings(service, row)
    )
    ctx = Context(db, principal.tenant_id, datetime.now(UTC), dict(row.state) if row else {}, deps)
    return await service.preview(ctx, settings)


@router.post("/automations/{kind}/run")
async def run_automation(
    kind: Kind, principal: Owner, db: TenantDb, deps: Annotated[Deps, Depends(get_deps)]
) -> RunOut:
    await limit(deps.redis, f"rl:automation-run:{principal.tenant_id}:{kind}", RUNS_PER_HOUR, 3600)
    try:
        run = await execute(principal.tenant_id, kind, "manual", deps)
    except BusyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "automation_busy") from exc
    except DisabledError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "automation_disabled") from exc
    assert run is not None  # noqa: S101
    return run_out(run)


@router.get("/automations/{kind}/runs")
async def list_runs(
    kind: Kind,
    principal: Member,
    db: TenantDb,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=100)] = 20,
) -> list[RunOut]:
    runs = await db.scalars(
        select(AutomationRun)
        .where(AutomationRun.kind == kind)
        .order_by(AutomationRun.created_at.desc())
        .limit(limit_)
    )
    return [run_out(run) for run in runs]


async def followup_rows(db: AsyncSession, *conditions: Any, limit_: int = 50) -> list[FollowupOut]:
    rows = await db.execute(
        select(Followup, Customer.name, Customer.channel)
        .join(Conversation, Conversation.id == Followup.conversation_id)
        .join(Customer, Customer.id == Conversation.customer_id)
        .where(*conditions)
        .order_by(Followup.created_at.desc())
        .limit(limit_)
    )
    return [
        FollowupOut(
            id=item.id,
            conversation_id=item.conversation_id,
            customer_name=name,
            channel=channel,
            text=item.text,
            status=item.status,
            created_at=item.created_at,
            sent_at=item.sent_at,
        )
        for item, name, channel in rows
    ]


@router.get("/followups")
async def list_followups(
    principal: Member,
    db: TenantDb,
    status_: Annotated[FollowupStatus | None, Query(alias="status")] = None,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=100)] = 50,
) -> list[FollowupOut]:
    conditions = [Followup.status == status_] if status_ else []
    return await followup_rows(db, *conditions, limit_=limit_)


async def pending_followup(db: AsyncSession, followup_id: uuid.UUID) -> Followup:
    followup = await db.scalar(select(Followup).where(Followup.id == followup_id).with_for_update())
    if followup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "followup_not_found")
    if followup.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "followup_decided")
    return followup


@router.post("/followups/{followup_id}/send")
async def send_followup(
    followup_id: uuid.UUID,
    principal: Member,
    db: TenantDb,
    deps: Annotated[Deps, Depends(get_deps)],
    body: FollowupSendIn | None = None,
) -> FollowupOut:
    await limit(deps.redis, f"rl:followup-send:{principal.tenant_id}", SENDS_PER_HOUR, 3600)
    followup = await pending_followup(db, followup_id)
    if await db.scalar(select(Tenant.bot_paused)):
        raise HTTPException(status.HTTP_409_CONFLICT, "bot_paused")
    user_id = None if principal.actor_id else principal.user_id
    await deliver(db, followup, deps, datetime.now(UTC), body.text if body else None, user_id)
    await db.flush()
    return (await followup_rows(db, Followup.id == followup_id))[0]


@router.post("/followups/{followup_id}/reject")
async def reject_followup(followup_id: uuid.UUID, principal: Member, db: TenantDb) -> FollowupOut:
    followup = await pending_followup(db, followup_id)
    followup.status = "rejected"
    followup.decided_by = None if principal.actor_id else principal.user_id
    await db.flush()
    return (await followup_rows(db, Followup.id == followup_id))[0]
