from sqlalchemy import text

from app.db.session import get_sessionmaker


async def release_idle_conversations(hours: int) -> int:
    async with get_sessionmaker()() as session, session.begin():
        released = await session.scalar(
            text("SELECT release_idle_conversations(:hours)"), {"hours": hours}
        )
    return int(released or 0)
