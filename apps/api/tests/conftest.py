import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.redis import get_redis

OWNER_URL = make_url(
    os.environ.get(
        "TEST_DATABASE_OWNER_URL",
        "postgresql+asyncpg://satushy:satushy@localhost:5433/satushy_test",
    )
)
APP_USER = "satushy_app_test"
APP_URL = OWNER_URL.set(username=APP_USER, password=APP_USER)
TEST_DB = OWNER_URL.database or ""
assert TEST_DB.endswith("_test"), "тесты пересоздают базу, имя должно оканчиваться на _test"

os.environ.update(
    ENV="test",
    REDIS_URL=os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
    DATABASE_URL=APP_URL.render_as_string(hide_password=False),
    DATABASE_OWNER_URL=OWNER_URL.render_as_string(hide_password=False),
)
for key, value in {
    "S3_ENDPOINT_URL": "http://localhost:9000",
    "S3_ACCESS_KEY": "test",
    "S3_SECRET_KEY": "test",
    "FERNET_KEY": "test",
    "JWT_SECRET": "test",
}.items():
    os.environ.setdefault(key, value)


def alembic_config() -> Config:
    return Config(str(Path(__file__).parents[1] / "alembic.ini"))


async def _recreate_database() -> None:
    admin = create_async_engine(
        OWNER_URL.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": APP_USER}
        )
        if not exists:
            await conn.execute(
                text(f"CREATE ROLE {APP_USER} LOGIN PASSWORD '{APP_USER}' NOBYPASSRLS")
            )
    await admin.dispose()


@pytest.fixture(scope="session")
def database() -> None:
    asyncio.run(_recreate_database())
    command.upgrade(alembic_config(), "head")


@pytest.fixture
async def owner_engine(database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(OWNER_URL, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def redis() -> Redis:
    client = get_redis()
    await client.flushdb()
    return client
