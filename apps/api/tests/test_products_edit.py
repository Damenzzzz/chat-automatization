import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import FakeSender, create_user, login


async def _product(
    engine: AsyncEngine, tenant_id: uuid.UUID, name: str = "Пионы белые"
) -> uuid.UUID:
    async with engine.begin() as conn:
        result: uuid.UUID = await conn.scalar(
            text(
                "INSERT INTO products (tenant_id, name, sku, price, stock, embedding_stale)"
                " VALUES (:t, :n, 'P-1', 25000, 4, false) RETURNING id"
            ),
            {"t": tenant_id, "n": name},
        )
    return result


async def _row(engine: AsyncEngine, product_id: uuid.UUID) -> dict[str, Any]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT price, stock, is_active, embedding_stale, content_hash, updated_at"
                    " FROM products WHERE id = :i"
                ),
                {"i": product_id},
            )
        ).one()
    return dict(row._mapping)


async def test_owner_changes_price_and_stock(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    product_id = await _product(owner_engine, owner)
    before = await _row(owner_engine, product_id)

    response = await client.patch(f"/products/{product_id}", json={"price": 27000, "stock": 0})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["price"], body["stock"]) == (27000, 0)
    after = await _row(owner_engine, product_id)
    assert (after["price"], after["stock"], after["is_active"]) == (27000, 0, True)
    assert after["embedding_stale"] is False
    assert after["content_hash"] == before["content_hash"]
    assert after["updated_at"] > before["updated_at"]


async def test_only_passed_fields_change_and_null_means_unknown(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    product_id = await _product(owner_engine, owner)

    response = await client.patch(f"/products/{product_id}", json={"stock": None})

    assert response.status_code == 200
    row = await _row(owner_engine, product_id)
    assert (row["price"], row["stock"]) == (25000, None)


async def test_removed_product_leaves_catalog(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    product_id = await _product(owner_engine, owner)

    response = await client.patch(f"/products/{product_id}", json={"is_active": False})

    assert response.status_code == 200
    assert (await client.get("/products")).json()["total"] == 0
    back = await client.patch(f"/products/{product_id}", json={"is_active": True})
    assert back.status_code == 200
    assert (await client.get("/products")).json()["total"] == 1


@pytest.mark.parametrize(
    "body",
    [{}, {"price": -1}, {"stock": -5}, {"price": "дорого"}, {"is_active": None}, {"name": "x"}],
)
async def test_invalid_changes_are_rejected(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine, body: dict[str, object]
) -> None:
    product_id = await _product(owner_engine, owner)
    before = await _row(owner_engine, product_id)

    response = await client.patch(f"/products/{product_id}", json=body)

    assert response.status_code == 422
    assert await _row(owner_engine, product_id) == before


async def test_foreign_and_unknown_products_are_404(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    other, _, _ = await create_user(owner_engine, tenant_name="Другой")
    foreign = await _product(owner_engine, other)

    response = await client.patch(f"/products/{foreign}", json={"price": 1})
    assert response.status_code == 404
    assert (await _row(owner_engine, foreign))["price"] == 25000
    unknown = await client.patch(f"/products/{uuid.uuid4()}", json={"price": 1})
    assert unknown.status_code == 404


async def test_manager_cannot_change_products(
    client: AsyncClient, owner: uuid.UUID, sender: FakeSender, owner_engine: AsyncEngine
) -> None:
    product_id = await _product(owner_engine, owner)
    _, _, phone = await create_user(owner_engine, role="manager", tenant_id=owner)
    await login(client, sender, phone)

    response = await client.patch(f"/products/{product_id}", json={"price": 1})

    assert response.status_code == 403
    assert (await _row(owner_engine, product_id))["price"] == 25000
