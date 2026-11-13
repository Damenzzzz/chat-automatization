from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.prompt import money
from app.automations.base import (
    Context,
    Outcome,
    Preview,
    PreviewItem,
    Recipients,
    Service,
    web_url,
)
from app.channels.staff import staff_text
from app.models import Lead
from app.routers.leads import lead_number

REMEMBER_SECONDS = 7 * 24 * 3600
MAX_AGE = timedelta(days=3)
BATCH = 100


class LeadReminderSettings(BaseModel):
    hours: int = Field(default=2, ge=1, le=48)
    recipients: Recipients = "team"


async def stale_leads(ctx: Context, hours: int) -> list[Any]:
    rows = await ctx.session.execute(
        select(Lead.id, Lead.total_kzt, Lead.created_at)
        .where(
            Lead.status == "new",
            Lead.created_at < ctx.now - timedelta(hours=hours),
            Lead.created_at > ctx.now - MAX_AGE,
        )
        .order_by(Lead.created_at)
        .limit(BATCH)
    )
    return list(rows)


async def due_leads(ctx: Context) -> list[Any]:
    rows = await ctx.session.execute(
        select(Lead.id, Lead.total_kzt, Lead.remind_at)
        .where(Lead.status.in_(("new", "in_progress")), Lead.remind_at <= ctx.now)
        .order_by(Lead.remind_at)
        .limit(BATCH)
    )
    return list(rows)


def due_text(row: Any) -> str:
    total = money(int(row.total_kzt or 0))
    return f"Напоминание по заявке №{lead_number(row.id)} на {total}.\n{web_url('/leads?due=1')}"


class LeadReminders(Service[LeadReminderSettings]):
    kind = "lead_reminders"
    title = "Напоминания о заявках"
    description = (
        "Напоминает команде в Telegram о новой заявке, которую никто не взял,"
        " и о заявках, по которым менеджер поставил себе срок."
    )
    default_enabled = True
    settings_model = LeadReminderSettings

    async def preview(self, ctx: Context, settings: LeadReminderSettings) -> Preview:
        stale, due = await stale_leads(ctx, settings.hours), await due_leads(ctx)
        items = [
            PreviewItem(
                title=f"Заявка №{lead_number(row.id)} на {money(int(row.total_kzt or 0))}",
                detail=f"без ответа {int((ctx.now - row.created_at).total_seconds() // 3600)} ч",
                href="/leads?status=new",
            )
            for row in stale
        ] + [
            PreviewItem(
                title=f"Заявка №{lead_number(row.id)} на {money(int(row.total_kzt or 0))}",
                detail="подошёл срок напоминания",
                href="/leads?due=1",
            )
            for row in due
        ]
        return Preview(
            summary=f"Сейчас без ответа дольше {settings.hours} ч: {len(stale)},"
            f" с подошедшим сроком: {len(due)}. О каждой заявке напоминаем один раз.",
            items=items[:15],
        )

    async def run(self, ctx: Context, settings: LeadReminderSettings) -> Outcome:
        redis, stale_sent, due_sent = ctx.deps.redis, 0, 0
        for row in await stale_leads(ctx, settings.hours):
            if not await redis.set(f"lead-reminded:{row.id}", "1", nx=True, ex=REMEMBER_SECONDS):
                continue
            payload = {"total_kzt": row.total_kzt, "hours": settings.hours}
            await ctx.tell(staff_text("lead.stale", payload) or "", settings.recipients)
            stale_sent += 1
        for row in await due_leads(ctx):
            key = f"lead-remind-at:{row.id}:{int(row.remind_at.timestamp())}"
            if not await redis.set(key, "1", nx=True, ex=REMEMBER_SECONDS):
                continue
            await ctx.tell(due_text(row), settings.recipients)
            due_sent += 1
        details = {"stale": stale_sent, "due": due_sent}
        if not stale_sent and not due_sent:
            return Outcome("empty", "Напоминать не о чем", details)
        return Outcome(
            "ok", f"Напоминаний: без ответа — {stale_sent}, по сроку — {due_sent}", details
        )
