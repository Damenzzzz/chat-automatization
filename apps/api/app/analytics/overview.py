from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import Date, and_, case, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.analytics.period import Period, timezone
from app.models import Conversation, Lead, Message


@dataclass(frozen=True)
class Metrics:
    dialogs: int
    bot_resolved: int
    bot_resolved_share: float | None
    leads: int
    leads_total_kzt: int
    avg_response_ms: int | None


def _customer_messages(period: Period) -> Any:
    return and_(
        Message.role == "customer",
        Message.created_at >= period.start,
        Message.created_at < period.end,
        Conversation.sandbox.is_(False),
    )


async def collect_metrics(session: AsyncSession, period: Period) -> Metrics:
    manager = aliased(Message)
    active = (
        select(Conversation.id, Conversation.mode)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(_customer_messages(period))
        .distinct()
        .subquery()
    )
    without_human = and_(
        active.c.mode == "bot",
        ~exists().where(manager.conversation_id == active.c.id, manager.role == "manager"),
    )
    dialogs, resolved = (
        await session.execute(
            select(
                func.count(active.c.id),
                func.coalesce(func.sum(case((without_human, 1), else_=0)), 0),
            )
        )
    ).one()

    leads, leads_total = (
        await session.execute(
            select(func.count(Lead.id), func.coalesce(func.sum(Lead.total_kzt), 0))
            .outerjoin(Conversation, Conversation.id == Lead.conversation_id)
            .where(
                Lead.created_at >= period.start,
                Lead.created_at < period.end,
                Lead.status != "cancelled",
                Conversation.sandbox.isnot(True),
            )
        )
    ).one()

    latency = await session.scalar(
        select(func.avg(Message.latency_ms))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.role == "bot",
            Message.model.is_not(None),
            Message.created_at >= period.start,
            Message.created_at < period.end,
            Conversation.sandbox.is_(False),
        )
    )
    return Metrics(
        dialogs=int(dialogs),
        bot_resolved=int(resolved),
        bot_resolved_share=round(int(resolved) / int(dialogs), 4) if dialogs else None,
        leads=int(leads),
        leads_total_kzt=int(leads_total or 0),
        avg_response_ms=round(latency) if latency is not None else None,
    )


def change_percent(current: float | None, previous: float | None) -> float | None:
    if current is None or not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def compare(current: Metrics, previous: Metrics) -> dict[str, float | None]:
    now, before = asdict(current), asdict(previous)
    return {key: change_percent(now[key], before[key]) for key in now}


async def dialogs_by_day(session: AsyncSession, period: Period) -> list[tuple[date, int]]:
    day = cast(func.timezone(str(timezone()), Message.created_at), Date)
    rows = await session.execute(
        select(day.label("day"), func.count(func.distinct(Message.conversation_id)))
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(_customer_messages(period))
        .group_by("day")
    )
    counts = {row[0]: int(row[1]) for row in rows}
    return [(d, counts.get(d, 0)) for d in period.dates()]
