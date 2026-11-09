import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, text

from app.auth.identity import Identity
from app.auth.users import UserRef, find_user
from app.billing.ledger import get_balance
from app.core.queue import Queue
from app.db.session import tenant_session
from app.demo.activity import clear_demo_activity, demo_activity_fresh, seed_activity
from app.models import LedgerEntry, Product, User
from app.seed import DEMO_BALANCE_KZT, DEMO_TENANT_ID, seed_demo

DEMO_EMAIL = "demo@satushy.kz"
DEMO_LOCK = 0x5A7D_E1A0


@dataclass
class DemoProduct:
    id: uuid.UUID
    name: str
    sku: str | None
    price: int | None
    stock: int | None
    category: str | None


async def ensure_demo_shop(queue: Queue) -> None:
    async with tenant_session(DEMO_TENANT_ID) as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DEMO_LOCK})
        has_catalog = await session.scalar(select(func.count(Product.id)))
    if not has_catalog:
        await seed_demo()
        await queue.enqueue(
            "reindex_embeddings", str(DEMO_TENANT_ID), job_id=f"reindex:{DEMO_TENANT_ID}"
        )
    async with tenant_session(DEMO_TENANT_ID) as session:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DEMO_LOCK})
        if not await demo_activity_fresh(session):
            await clear_demo_activity(session)
            await seed_activity(session, DEMO_TENANT_ID)
        if await get_balance(session) < DEMO_BALANCE_KZT // 2:
            session.add(
                LedgerEntry(
                    tenant_id=DEMO_TENANT_ID,
                    type="topup",
                    amount_kzt=DEMO_BALANCE_KZT,
                    comment="демо-магазин",
                )
            )


async def demo_owner() -> UserRef:
    user = await find_user(Identity("email", DEMO_EMAIL))
    if user is not None:
        return user
    async with tenant_session(DEMO_TENANT_ID) as session:
        row = User(tenant_id=DEMO_TENANT_ID, role="owner", email=DEMO_EMAIL)
        session.add(row)
        await session.flush()
        return UserRef(row.id, DEMO_TENANT_ID, row.role, True)


async def mentioned_products(reply: str) -> list[DemoProduct]:
    folded = reply.casefold()
    async with tenant_session(DEMO_TENANT_ID) as session:
        rows = list(await session.scalars(select(Product).where(Product.is_active)))
    found = [
        p
        for p in rows
        if p.name.casefold() in folded or (p.sku and re.search(re.escape(p.sku), reply))
    ]
    found.sort(key=lambda p: folded.find(p.name.casefold()))
    return [DemoProduct(p.id, p.name, p.sku, p.price, p.stock, p.category) for p in found[:3]]
