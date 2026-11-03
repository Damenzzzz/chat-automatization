import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture
async def entry(owner_engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    async with owner_engine.begin() as conn:
        tenant_id = await conn.scalar(
            text("INSERT INTO tenants (name) VALUES ('Баланс') RETURNING id")
        )
        entry_id = await conn.scalar(
            text(
                "INSERT INTO ledger (tenant_id, type, amount_kzt, cost_usd) "
                "VALUES (:t, 'charge', -15, 0.003100) RETURNING id"
            ),
            {"t": tenant_id},
        )
    return tenant_id, entry_id


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE ledger SET amount_kzt = 0 WHERE id = :id",
        "DELETE FROM ledger WHERE id = :id",
    ],
)
async def test_ledger_is_append_only(
    owner_engine: AsyncEngine, entry: tuple[uuid.UUID, uuid.UUID], sql: str
) -> None:
    with pytest.raises(DBAPIError, match="append-only"):
        async with owner_engine.begin() as conn:
            await conn.execute(text(sql), {"id": entry[1]})


async def test_tenant_with_ledger_cannot_be_deleted(
    owner_engine: AsyncEngine, entry: tuple[uuid.UUID, uuid.UUID]
) -> None:
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": entry[0]})


async def test_charge_must_be_negative(
    owner_engine: AsyncEngine, entry: tuple[uuid.UUID, uuid.UUID]
) -> None:
    with pytest.raises(IntegrityError):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO ledger (tenant_id, type, amount_kzt) VALUES (:t, 'charge', 10)"),
                {"t": entry[0]},
            )
