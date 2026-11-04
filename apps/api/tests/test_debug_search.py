import uuid

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.identity import IdentityIn
from app.cli import create_admin
from app.mlclient import get_ml_client
from tests.conftest import FakeSender, login, random_phone
from tests.fake_ml import FakeML, make_shop


async def _shop(engine: AsyncEngine) -> uuid.UUID:
    return await make_shop(
        engine,
        [
            {"sku": "PN-001", "name": "Розовые пионы", "price": 32000, "stock": 6},
            {"sku": "RS-101", "name": "Красные розы", "price": 24000, "stock": 0},
        ],
        kb=[{"source": "delivery", "title": "Доставка", "text": "Доставка по Алматы"}],
    )


async def test_admin_debug_search(
    app: FastAPI, client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    app.dependency_overrides[get_ml_client] = FakeML
    shop_id = await _shop(owner_engine)
    phone = random_phone()
    await create_admin(IdentityIn(phone=phone))
    await login(client, sender, phone)

    response = await client.get(
        "/debug/search", params={"q": "розовые пионы", "tenant_id": str(shop_id), "in_stock": 1}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lang"] == "ru"
    assert body["filters"] == {"in_stock": True}
    assert body["candidates"]["vector"] == 1
    top = body["products"][0]
    assert top["sku"] == "PN-001"
    assert top["price"] == 32000
    assert set(top["reasons"]) == {"vector", "fts"}
    assert all(p["stock"] != 0 for p in body["products"])
    assert body["kb"][0]["source"] == "delivery"

    async with owner_engine.connect() as conn:
        logged = await conn.scalar(
            text("SELECT count(*) FROM search_log WHERE tenant_id = :t"), {"t": shop_id}
        )
    assert logged == 0

    missing = await client.get("/debug/search", params={"q": "x", "tenant_id": str(uuid.uuid4())})
    assert missing.status_code == 404


async def test_debug_search_admin_only(app: FastAPI, client: AsyncClient, owner: uuid.UUID) -> None:
    app.dependency_overrides[get_ml_client] = FakeML
    response = await client.get("/debug/search", params={"q": "пионы", "tenant_id": str(owner)})
    assert response.status_code == 403


async def test_debug_search_requires_login(client: AsyncClient) -> None:
    response = await client.get("/debug/search", params={"q": "x", "tenant_id": str(uuid.uuid4())})
    assert response.status_code == 401
