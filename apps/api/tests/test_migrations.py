import asyncio

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from tests.conftest import OWNER_URL, alembic_config


async def _public_tables() -> set[str]:
    engine = create_async_engine(OWNER_URL, poolclass=NullPool)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        names = {r[0] for r in rows}
    await engine.dispose()
    return names - {"alembic_version"}


def test_upgrade_downgrade_roundtrip(database: None) -> None:
    cfg = alembic_config()
    expected = set(Base.metadata.tables)

    command.downgrade(cfg, "base")
    assert asyncio.run(_public_tables()) == set()

    command.upgrade(cfg, "head")
    assert asyncio.run(_public_tables()) == expected


def test_models_match_migrations(database: None) -> None:
    command.check(alembic_config())
