import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import CursorResult, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.base import Base
from app.db.session import get_sessionmaker, tenant_session
from tests.conftest import APP_USER


@dataclass
class Shop:
    tenant_id: uuid.UUID
    product_id: uuid.UUID


async def _shop(engine: AsyncEngine, name: str) -> Shop:
    async with engine.begin() as conn:
        tenant_id = await conn.scalar(
            text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"), {"n": name}
        )
        product_id = await conn.scalar(
            text(
                "INSERT INTO products (tenant_id, name, price, stock) "
                "VALUES (:t, :n, 10000, 3) RETURNING id"
            ),
            {"t": tenant_id, "n": f"Букет {name}"},
        )
    return Shop(tenant_id, product_id)


@pytest.fixture
async def shops(owner_engine: AsyncEngine) -> tuple[Shop, Shop]:
    return await _shop(owner_engine, "A"), await _shop(owner_engine, "B")


async def test_tenant_sees_only_own_rows(shops: tuple[Shop, Shop]) -> None:
    a, _ = shops
    async with tenant_session(a.tenant_id) as session:
        products = set((await session.scalars(text("SELECT id FROM products"))).all())
        tenants = set((await session.scalars(text("SELECT id FROM tenants"))).all())

    assert products == {a.product_id}
    assert tenants == {a.tenant_id}


async def test_tenant_cannot_modify_other_tenant(
    shops: tuple[Shop, Shop], owner_engine: AsyncEngine
) -> None:
    a, b = shops
    async with tenant_session(a.tenant_id) as session:
        updated: CursorResult[tuple[()]] = await session.execute(  # type: ignore[assignment]
            text("UPDATE products SET price = 1 WHERE id = :id"), {"id": b.product_id}
        )
        deleted: CursorResult[tuple[()]] = await session.execute(  # type: ignore[assignment]
            text("DELETE FROM products WHERE id = :id"), {"id": b.product_id}
        )
    assert updated.rowcount == 0
    assert deleted.rowcount == 0

    async with owner_engine.connect() as conn:
        price = await conn.scalar(
            text("SELECT price FROM products WHERE id = :id"), {"id": b.product_id}
        )
    assert price == 10000


async def test_tenant_cannot_insert_into_other_tenant(shops: tuple[Shop, Shop]) -> None:
    a, b = shops
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(a.tenant_id) as session:
            await session.execute(
                text("INSERT INTO products (tenant_id, name) VALUES (:t, 'чужой')"),
                {"t": b.tenant_id},
            )


async def test_no_tenant_context_sees_nothing(shops: tuple[Shop, Shop]) -> None:
    async with get_sessionmaker()() as session:
        count = await session.scalar(text("SELECT count(*) FROM products"))
    assert count == 0


async def test_app_role_cannot_change_ledger(shops: tuple[Shop, Shop]) -> None:
    a, _ = shops
    async with tenant_session(a.tenant_id) as session:
        await session.execute(
            text("INSERT INTO ledger (tenant_id, type, amount_kzt) VALUES (:t, 'topup', 5000)"),
            {"t": a.tenant_id},
        )
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(a.tenant_id) as session:
            await session.execute(text("UPDATE ledger SET amount_kzt = 1"))


async def test_every_table_has_rls(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_policies p "
                "ON p.tablename = c.relname AND p.policyname = 'tenant_isolation' "
                "WHERE c.relrowsecurity AND c.relnamespace = 'public'::regnamespace"
            )
        )
        protected = {r[0] for r in rows}
        bypass = await conn.scalar(
            text("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = :r"),
            {"r": APP_USER},
        )

    assert protected == set(Base.metadata.tables)
    assert bypass is False
