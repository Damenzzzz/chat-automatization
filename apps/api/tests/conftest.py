import asyncio
import os
import secrets
import string
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient, Response
from redis.asyncio import Redis
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.deps import get_code_sender
from app.auth.identity import Identity
from app.core.redis import get_redis
from app.core.storage import MemoryStorage, get_storage

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
    "JWT_SECRET": "test-secret-for-pytest-only-0123456789",
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


class FakeSender:
    def __init__(self) -> None:
        self.codes: dict[str, str] = {}

    async def send(self, identity: Identity, code: str) -> None:
        self.codes[identity.value] = code


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
async def client(
    database: None, redis: Redis, sender: FakeSender, storage: MemoryStorage
) -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_code_sender] = lambda: sender
    app.dependency_overrides[get_storage] = lambda: storage
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def random_phone() -> str:
    return "+7700" + "".join(secrets.choice(string.digits) for _ in range(7))


async def create_user(
    engine: AsyncEngine,
    *,
    role: str = "owner",
    phone: str | None = None,
    tenant_id: uuid.UUID | None = None,
    tenant_name: str = "Тестовый магазин",
) -> tuple[uuid.UUID, uuid.UUID, str]:
    phone = phone or random_phone()
    async with engine.begin() as conn:
        if tenant_id is None:
            tenant_id = await conn.scalar(
                text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"), {"n": tenant_name}
            )
        user_id = await conn.scalar(
            text("INSERT INTO users (tenant_id, phone, role) VALUES (:t, :p, :r) RETURNING id"),
            {"t": tenant_id, "p": phone, "r": role},
        )
    assert tenant_id is not None
    return tenant_id, user_id, phone


async def login(client: AsyncClient, sender: FakeSender, phone: str) -> Response:
    await client.post("/auth/request-code", json={"phone": phone})
    return await client.post("/auth/verify", json={"phone": phone, "code": sender.codes[phone]})


@pytest.fixture
async def owner(client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine) -> uuid.UUID:
    tenant_id, _, phone = await create_user(owner_engine)
    await login(client, sender, phone)
    return tenant_id
