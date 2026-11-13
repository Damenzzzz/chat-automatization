import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.analytics.period import timezone
from app.automations.base import (
    Context,
    Deps,
    Outcome,
    Preview,
    PreviewItem,
    Service,
    plural,
    web_url,
)
from app.channels.types import ChannelError, OutgoingMessage
from app.core.poke import poke
from app.models import Conversation, Customer, Followup, Lead, Message, SearchLog, Tenant

log = structlog.get_logger()

# WhatsApp и Instagram разрешают писать первым только 24 часа после сообщения покупателя.
WINDOW = timedelta(hours=23)
REPEAT_AFTER = timedelta(days=7)
BATCH = 20
DEFAULT_TEXT = (
    "Здравствуйте! Вы недавно спрашивали у нас про товар."
    " Подсказать что-нибудь ещё или помочь оформить заказ?"
)
FollowupChannel = Literal["telegram", "whatsapp", "web"]
DEFAULT_CHANNELS: tuple[FollowupChannel, ...] = ("telegram", "whatsapp")


class FollowupSettings(BaseModel):
    delay_hours: int = Field(default=3, ge=1, le=20)
    mode: Literal["approve", "auto"] = "approve"
    text: str = Field(default=DEFAULT_TEXT, min_length=10, max_length=500)
    channels: list[FollowupChannel] = Field(default_factory=lambda: list(DEFAULT_CHANNELS))
    quiet_from: int = Field(default=21, ge=0, le=23)
    quiet_to: int = Field(default=9, ge=0, le=23)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("channels")
    @classmethod
    def channels_once(cls, value: list[FollowupChannel]) -> list[FollowupChannel]:
        if not value:
            raise ValueError("at least one channel")
        return sorted(set(value))


def quiet(settings: FollowupSettings, now: datetime) -> bool:
    hour = now.astimezone(timezone()).hour
    start, end = settings.quiet_from, settings.quiet_to
    if start == end:
        return False
    return start <= hour < end if start < end else hour >= start or hour < end


def last_customer_at() -> Any:
    return (
        select(func.max(Message.created_at))
        .where(Message.conversation_id == Conversation.id, Message.role == "customer")
        .scalar_subquery()
        .correlate(Conversation)
    )


def candidates(settings: FollowupSettings, now: datetime) -> Select[Any]:
    last = (
        select(Message.role.label("role"))
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .lateral("last_message")
    )
    silent_since = last_customer_at()
    searched = (
        select(SearchLog.id)
        .where(
            SearchLog.conversation_id == Conversation.id,
            SearchLog.kind == "product",
            SearchLog.result_count > 0,
            SearchLog.created_at > now - timedelta(hours=24),
        )
        .exists()
    )
    ordered = (
        select(Lead.id)
        .where(Lead.conversation_id == Conversation.id, Lead.created_at > now - REPEAT_AFTER)
        .exists()
    )
    asked = (
        select(Followup.id)
        .where(
            Followup.conversation_id == Conversation.id, Followup.created_at > now - REPEAT_AFTER
        )
        .exists()
    )
    columns: tuple[Any, ...] = (
        Conversation.id,
        Customer.name,
        Customer.channel,
        silent_since.label("silent_since"),
    )
    return (
        select(*columns)
        .join(Customer, Customer.id == Conversation.customer_id)
        .outerjoin(last, true())
        .where(
            Conversation.sandbox.is_(False),
            Conversation.status == "open",
            Conversation.mode == "bot",
            Conversation.channel_id.is_not(None),
            Conversation.paused_reason.is_(None),
            Customer.channel.in_(settings.channels),
            last.c.role == "bot",
            silent_since <= now - timedelta(hours=settings.delay_hours),
            silent_since > now - WINDOW,
            searched,
            ~ordered,
            ~asked,
        )
        .order_by(silent_since)
        .limit(BATCH)
    )


async def blocker(session: AsyncSession, followup: Followup, now: datetime) -> str | None:
    conversation = await session.get(Conversation, followup.conversation_id)
    if (
        conversation is None
        or conversation.sandbox
        or conversation.status != "open"
        or conversation.channel_id is None
    ):
        return "dialog_closed"
    if conversation.mode != "bot":
        return "dialog_with_manager"
    silent_since = await session.scalar(
        select(func.max(Message.created_at)).where(
            Message.conversation_id == conversation.id, Message.role == "customer"
        )
    )
    if silent_since is None or silent_since <= now - WINDOW:
        return "window_closed"
    if silent_since > followup.created_at:
        return "customer_replied"
    return None


async def deliver(
    session: AsyncSession,
    followup: Followup,
    deps: Deps,
    now: datetime,
    text: str | None = None,
    user_id: uuid.UUID | None = None,
) -> str:
    """Отправляет напоминание покупателю и возвращает новый статус записи."""
    followup.decided_by = user_id
    if await blocker(session, followup, now):
        followup.status = "expired"
        return followup.status
    conversation = await session.get(Conversation, followup.conversation_id)
    assert conversation is not None and conversation.channel_id is not None  # noqa: S101
    external_id = await session.scalar(
        select(Customer.external_id).where(Customer.id == conversation.customer_id)
    )
    body = (text or followup.text).strip()
    step: dict[str, Any] = {"node": "followup", "delivered": True}
    if user_id:
        step["user_id"] = str(user_id)
    try:
        await deps.outbound.send(
            conversation.channel_id, str(external_id), OutgoingMessage(text=body)
        )
    except ChannelError as exc:
        log.warning("followup.send_failed", conversation_id=str(conversation.id), error=str(exc))
        followup.status = "failed"
        return followup.status
    session.add(
        Message(
            tenant_id=followup.tenant_id,
            conversation_id=conversation.id,
            role="bot",
            content=body,
            trace={"steps": [step]},
        )
    )
    conversation.last_message_at = now
    followup.text, followup.status, followup.sent_at = body, "sent", now
    await session.flush()
    await poke(followup.tenant_id)
    if deps.remember is not None:
        await deps.remember(conversation.id, body)
    return followup.status


async def expire_stale(session: AsyncSession, now: datetime) -> int:
    pending = list(await session.scalars(select(Followup).where(Followup.status == "pending")))
    expired = 0
    for followup in pending:
        if await blocker(session, followup, now):
            followup.status = "expired"
            expired += 1
    return expired


def people(count: int) -> str:
    return f"{count} {plural(count, 'покупателю', 'покупателям', 'покупателям')}"


class FollowupService(Service[FollowupSettings]):
    kind = "followup"
    title = "Возврат покупателя"
    description = (
        "Покупатель спросил про товар и замолчал — через несколько часов бот вежливо"
        " напомнит о себе. По умолчанию каждое сообщение сначала одобряете вы."
    )
    settings_model = FollowupSettings

    def due(
        self,
        settings: FollowupSettings,
        state: dict[str, Any],
        last_run_at: datetime | None,
        ctx_now: datetime,
    ) -> bool:
        return not quiet(settings, ctx_now)

    async def preview(self, ctx: Context, settings: FollowupSettings) -> Preview:
        rows = (await ctx.session.execute(candidates(settings, ctx.now))).all()
        return Preview(
            summary=f"Сейчас напоминание получили бы: {people(len(rows))}.",
            text=settings.text,
            items=[
                PreviewItem(
                    title=row.name or "Покупатель без имени",
                    detail=f"{row.channel}, молчит"
                    f" {int((ctx.now - row.silent_since).total_seconds() // 3600)} ч",
                    href=f"/dialogs?id={row.id}",
                )
                for row in rows
            ],
        )

    async def run(self, ctx: Context, settings: FollowupSettings) -> Outcome:
        expired = await expire_stale(ctx.session, ctx.now)
        if await ctx.session.scalar(select(Tenant.bot_paused)):
            return Outcome("empty", "Бот на паузе — покупателям не пишем", {"expired": expired})
        if quiet(settings, ctx.now):
            return Outcome("empty", "Тихие часы — покупателям не пишем", {"expired": expired})
        rows = (await ctx.session.execute(candidates(settings, ctx.now))).all()
        details: dict[str, Any] = {"found": len(rows), "expired": expired}
        if not rows:
            return Outcome("empty", "Затихших диалогов нет", details)
        created = [
            Followup(tenant_id=ctx.tenant_id, conversation_id=row.id, text=settings.text)
            for row in rows
        ]
        ctx.session.add_all(created)
        await ctx.session.flush()
        for followup in created:
            await ctx.session.refresh(followup)
        if settings.mode == "approve":
            await ctx.tell(
                f"Напоминания покупателям ждут одобрения: {len(created)}.\n"
                f"{web_url('/services?service=followup')}",
                "team",
            )
            return Outcome("ok", f"Ждут вашего одобрения: {len(created)}", details)
        statuses = [await deliver(ctx.session, item, ctx.deps, ctx.now) for item in created]
        sent = statuses.count("sent")
        details |= {"sent": sent, "failed": statuses.count("failed")}
        return Outcome("ok", f"Напоминание отправлено {people(sent)}", details)


async def reject_pending(session: AsyncSession) -> int:
    result = await session.execute(
        update(Followup).where(Followup.status == "pending").values(status="rejected")
    )
    return int(getattr(result, "rowcount", 0) or 0)
