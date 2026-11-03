from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.cookies import ACCESS_COOKIE
from app.auth.deps import Principal, TenantDb, get_code_sender, require_role
from tests.conftest import FakeSender, create_user, login


@pytest.fixture
async def app_client(
    database: None, redis: Redis, sender: FakeSender
) -> AsyncIterator[AsyncClient]:
    from app.main import create_app

    app: FastAPI = create_app()
    app.dependency_overrides[get_code_sender] = lambda: sender

    @app.get("/_test/owner-only")
    async def owner_only(
        principal: Annotated[Principal, Depends(require_role("owner"))],
    ) -> dict[str, str]:
        return {"role": principal.role}

    @app.get("/_test/products")
    async def products(db: TenantDb) -> list[str]:
        return list((await db.scalars(text("SELECT name FROM products ORDER BY name"))).all())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_me_requires_auth(app_client: AsyncClient) -> None:
    assert (await app_client.get("/me")).status_code == 401
    app_client.cookies.set(ACCESS_COOKIE, "garbage")
    assert (await app_client.get("/me")).status_code == 401


async def test_me_returns_tenant(
    app_client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, user_id, phone = await create_user(owner_engine, tenant_name="Магазин А")
    await login(app_client, sender, phone)

    body = (await app_client.get("/me")).json()
    assert body["tenant_id"] == str(tenant_id)
    assert body["user_id"] == str(user_id)
    assert body["tenant_name"] == "Магазин А"
    assert body["impersonated_by"] is None


async def test_require_role(
    app_client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_id, _, owner_phone = await create_user(owner_engine)
    *_, manager_phone = await create_user(owner_engine, role="manager", tenant_id=tenant_id)

    await login(app_client, sender, manager_phone)
    assert (await app_client.get("/_test/owner-only")).status_code == 403

    await login(app_client, sender, owner_phone)
    assert (await app_client.get("/_test/owner-only")).json() == {"role": "owner"}


async def test_token_of_tenant_a_does_not_see_tenant_b(
    app_client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    tenant_a, _, phone_a = await create_user(owner_engine)
    tenant_b, *_ = await create_user(owner_engine)
    async with owner_engine.begin() as conn:
        for tenant, name in ((tenant_a, "Товар А"), (tenant_b, "Товар Б")):
            await conn.execute(
                text("INSERT INTO products (tenant_id, name) VALUES (:t, :n)"),
                {"t": tenant, "n": name},
            )

    await login(app_client, sender, phone_a)
    assert (await app_client.get("/_test/products")).json() == ["Товар А"]


async def test_disabled_user_loses_access(
    app_client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    _, user_id, phone = await create_user(owner_engine)
    await login(app_client, sender, phone)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": user_id}
        )

    assert (await app_client.get("/me")).status_code == 401
