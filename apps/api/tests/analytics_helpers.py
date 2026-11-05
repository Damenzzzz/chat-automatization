import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

ALMATY = ZoneInfo("Asia/Almaty")


def at(day: date, hour: int = 12) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=ALMATY).astimezone(UTC)


async def dialog(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    moment: datetime,
    *,
    mode: str = "bot",
    sandbox: bool = False,
    manager: bool = False,
    latency: int | None = 1000,
) -> uuid.UUID:
    async with engine.begin() as conn:
        customer = await conn.scalar(
            text(
                "INSERT INTO customers (tenant_id, channel, external_id) VALUES (:t, 'web', :e)"
                " RETURNING id"
            ),
            {"t": tenant_id, "e": uuid.uuid4().hex},
        )
        conversation: uuid.UUID = await conn.scalar(
            text(
                "INSERT INTO conversations (tenant_id, customer_id, mode, sandbox)"
                " VALUES (:t, :c, :m, :s) RETURNING id"
            ),
            {"t": tenant_id, "c": customer, "m": mode, "s": sandbox},
        )
        insert = text(
            "INSERT INTO messages (tenant_id, conversation_id, role, content, model, latency_ms,"
            " created_at) VALUES (:t, :c, :r, 'x', :model, :lat, :at)"
        )
        base = {"t": tenant_id, "c": conversation}
        await conn.execute(
            insert, {**base, "r": "customer", "model": None, "lat": None, "at": moment}
        )
        if latency is not None:
            await conn.execute(
                insert,
                {
                    **base,
                    "r": "bot",
                    "model": "gemini-3.5-flash-lite",
                    "lat": latency,
                    "at": moment + timedelta(seconds=5),
                },
            )
        if manager:
            await conn.execute(
                insert,
                {
                    **base,
                    "r": "manager",
                    "model": None,
                    "lat": None,
                    "at": moment + timedelta(minutes=5),
                },
            )
    return conversation


async def lead(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    moment: datetime,
    total: int,
    status: str = "new",
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO leads (tenant_id, conversation_id, total_kzt, status, created_at)"
                " VALUES (:t, :c, :a, :s, :at)"
            ),
            {"t": tenant_id, "c": conversation_id, "a": total, "s": status, "at": moment},
        )
