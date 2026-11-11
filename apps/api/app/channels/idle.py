import uuid

from sqlalchemy import text

from app.db.session import get_sessionmaker


async def release_idle_conversations(hours: int) -> int:
    async with get_sessionmaker()() as session, session.begin():
        released = await session.scalar(
            text("SELECT release_idle_conversations(:hours)"), {"hours": hours}
        )
    return int(released or 0)


async def retire_idle_conversations(idle_days: int, sandbox_days: int) -> list[uuid.UUID]:
    async with get_sessionmaker()() as session, session.begin():
        rows = await session.scalars(
            text("SELECT * FROM retire_idle_conversations(:idle, :sandbox)"),
            {"idle": idle_days, "sandbox": sandbox_days},
        )
        return list(rows)


async def purge_search_log(keep_days: int) -> int:
    async with get_sessionmaker()() as session, session.begin():
        removed = await session.scalar(text("SELECT purge_search_log(:days)"), {"days": keep_days})
    return int(removed or 0)


async def stale_new_leads(wait_hours: int) -> list[tuple[uuid.UUID, uuid.UUID, int]]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            text("SELECT * FROM stale_new_leads(:hours)"), {"hours": wait_hours}
        )
        return [(r.tenant_id, r.lead_id, int(r.total_kzt or 0)) for r in rows]
