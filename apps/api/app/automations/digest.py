from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompt import money
from app.analytics.overview import collect_metrics
from app.analytics.period import Period, timezone
from app.automations.base import Context, Outcome, Preview, Recipients, Service, web_url
from app.automations.stock import StockSettings, low_stock_query
from app.models import Automation, Conversation, Lead, Message, Tenant, Unanswered

Section = Literal["dialogs", "leads", "money", "waiting", "unanswered", "stock"]
ALL_SECTIONS: list[Section] = ["dialogs", "leads", "money", "waiting", "unanswered", "stock"]


class DigestSettings(BaseModel):
    hour: int = Field(default=9, ge=0, le=23)
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    sections: list[Section] = Field(default_factory=lambda: list(ALL_SECTIONS), min_length=1)
    recipients: Recipients = "owner"

    @field_validator("weekdays")
    @classmethod
    def weekdays_are_days(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value):
            raise ValueError("weekday out of range")
        return sorted(set(value))

    @field_validator("sections")
    @classmethod
    def sections_once(cls, value: list[Section]) -> list[Section]:
        return [section for section in ALL_SECTIONS if section in value]


async def waiting_now(session: AsyncSession) -> int:
    last_role = (
        select(Message.role)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .scalar_subquery()
        .correlate(Conversation)
    )
    count = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.sandbox.is_(False),
            Conversation.status == "open",
            Conversation.mode == "human",
            last_role == "customer",
        )
    )
    return int(count or 0)


async def low_stock_count(session: AsyncSession) -> int:
    row = await session.scalar(select(Automation).where(Automation.kind == "stock"))
    try:
        settings = StockSettings.model_validate(row.settings if row else {})
    except ValueError:
        settings = StockSettings()
    query = low_stock_query(settings).subquery()
    return int(await session.scalar(select(func.count()).select_from(query)) or 0)


async def digest_text(session: AsyncSession, settings: DigestSettings, now: datetime) -> str:
    day = now.astimezone(timezone()).date() - timedelta(days=1)
    name = await session.scalar(select(Tenant.name)) or "магазин"
    lines = [f"«{name}»: сводка за {day:%d.%m}"]
    wanted = set(settings.sections)
    if wanted & {"dialogs", "leads", "money"}:
        metrics = await collect_metrics(session, Period(day, day))
        if "dialogs" in wanted:
            share = metrics.bot_resolved_share
            percent = f" ({round(share * 100)}%)" if share is not None else ""
            lines.append(
                f"Диалогов: {metrics.dialogs}, бот ответил сам: {metrics.bot_resolved}{percent}"
            )
        if "leads" in wanted:
            lines.append(
                f"Заявок: {metrics.leads} на {money(metrics.leads_total_kzt)},"
                f" выполнено: {metrics.leads_done}"
            )
        if "money" in wanted:
            lines.append(f"Расход на ответы бота: {money(metrics.spent_kzt)}")
    if "waiting" in wanted:
        fresh = await session.scalar(
            select(func.count()).select_from(Lead).where(Lead.status == "new")
        )
        overdue = await session.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.status.in_(("new", "in_progress")), Lead.remind_at <= now)
        )
        lines.append(
            f"Ждут вас сейчас: диалогов — {await waiting_now(session)},"
            f" новых заявок — {int(fresh or 0)}, напоминаний по заявкам — {int(overdue or 0)}"
        )
    if "unanswered" in wanted:
        unknown = await session.scalar(
            select(func.count())
            .select_from(Unanswered)
            .where(
                Unanswered.resolved_at.is_(None), Unanswered.created_at > now - timedelta(days=7)
            )
        )
        lines.append(f"Бот не знал ответа за неделю: {int(unknown or 0)}")
    if "stock" in wanted:
        lines.append(f"Товаров на исходе: {await low_stock_count(session)}")
    lines.append(web_url("/overview"))
    return "\n".join(lines)


class Digest(Service[DigestSettings]):
    kind = "digest"
    title = "Сводка за день"
    description = (
        "Раз в день присылает владельцу итоги вчерашнего дня и то, что ждёт ответа прямо сейчас."
    )
    settings_model = DigestSettings
    cooldown = 6 * 3600

    def due(
        self,
        settings: DigestSettings,
        state: dict[str, Any],
        last_run_at: datetime | None,
        ctx_now: datetime,
    ) -> bool:
        local = ctx_now.astimezone(timezone())
        return (
            local.weekday() in settings.weekdays
            and local.hour >= settings.hour
            and state.get("last_date") != local.date().isoformat()
        )

    async def preview(self, ctx: Context, settings: DigestSettings) -> Preview:
        text = await digest_text(ctx.session, settings, ctx.now)
        return Preview(
            summary=f"Так выглядит сводка. Отправка — каждый день в {settings.hour}:00.", text=text
        )

    async def run(self, ctx: Context, settings: DigestSettings) -> Outcome:
        text = await digest_text(ctx.session, settings, ctx.now)
        sent = await ctx.tell(text, settings.recipients)
        ctx.note("digest", text)
        if not ctx.manual:
            ctx.state["last_date"] = ctx.local.date().isoformat()
        where = (
            f"в Telegram, получателей: {sent}" if sent else "в уведомления (Telegram не привязан)"
        )
        return Outcome("ok", f"Сводка отправлена {where}", {"sent": sent})
