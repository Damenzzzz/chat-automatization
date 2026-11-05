import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.identity import IdentityIn
from app.cli import create_admin
from tests.conftest import FakeSender, login, random_phone


async def login_admin(client: AsyncClient, sender: FakeSender) -> uuid.UUID:
    phone = random_phone()
    user_id = await create_admin(IdentityIn(phone=phone))
    await login(client, sender, phone)
    return user_id


async def topup(engine: AsyncEngine, tenant_id: uuid.UUID, amount: int) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO ledger (tenant_id, type, amount_kzt) VALUES (:t, 'topup', :a)"),
            {"t": tenant_id, "a": amount},
        )


async def balance(engine: AsyncEngine, tenant_id: uuid.UUID) -> int:
    async with engine.connect() as conn:
        value = await conn.scalar(
            text("SELECT coalesce(sum(amount_kzt), 0) FROM ledger WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    return int(value or 0)


async def charges(engine: AsyncEngine, tenant_id: uuid.UUID) -> list[int]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT amount_kzt FROM ledger WHERE tenant_id = :t AND type = 'charge'"
                " ORDER BY created_at"
            ),
            {"t": tenant_id},
        )
        return [r[0] for r in rows]
