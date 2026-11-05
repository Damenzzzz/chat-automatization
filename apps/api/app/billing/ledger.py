import math
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.pricing import MIN_REPLY_PRICE_KZT, load_pricing, reply_price_kzt, turn_cost
from app.models import LedgerEntry

ESTIMATE_WINDOW = 20


@dataclass(frozen=True)
class Charge:
    price_kzt: int
    charged_kzt: int
    balance_before: int
    balance_after: int
    cost_usd: Decimal

    @property
    def clipped(self) -> bool:
        return self.charged_kzt < self.price_kzt


async def get_balance(session: AsyncSession) -> int:
    value = await session.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_kzt), 0)))
    return int(value or 0)


async def lock_ledger(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"ledger:{tenant_id}"},
    )


async def estimated_reply_price(session: AsyncSession) -> int:
    recent = (
        select(LedgerEntry.amount_kzt)
        .where(LedgerEntry.type == "charge")
        .order_by(LedgerEntry.created_at.desc())
        .limit(ESTIMATE_WINDOW)
        .subquery()
    )
    average = await session.scalar(select(func.avg(recent.c.amount_kzt)))
    if average is None:
        return MIN_REPLY_PRICE_KZT
    return max(MIN_REPLY_PRICE_KZT, math.ceil(abs(Decimal(average))))


async def charge_reply(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    message_id: uuid.UUID,
    usage: list[dict[str, Any]],
    model: str | None,
    cost: Decimal,
) -> Charge:
    await lock_ledger(session, tenant_id)
    pricing = await load_pricing(session)
    price = reply_price_kzt(cost, pricing)
    before = await get_balance(session)
    amount = min(price, max(before, 0))
    if amount > 0:
        session.add(
            LedgerEntry(
                tenant_id=tenant_id,
                type="charge",
                amount_kzt=-amount,
                cost_usd=cost,
                model=model,
                tokens_in=sum(u["tokens_in"] for u in usage),
                tokens_out=sum(u["tokens_out"] for u in usage),
                message_id=message_id,
                comment=f"цена {price} ₸, списан остаток" if amount < price else None,
            )
        )
        await session.flush()
    return Charge(price, amount, before, before - amount, cost)


async def reply_cost(session: AsyncSession, usage: list[dict[str, Any]]) -> Decimal:
    return turn_cost(usage, await load_pricing(session))
