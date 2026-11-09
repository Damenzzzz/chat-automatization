import asyncio
import csv
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.queue import get_queue
from app.db.session import tenant_session
from app.models import BotProfile, KbChunk, LedgerEntry, Product, Tenant

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_TENANT_ID = uuid.UUID("7e1a1700-0000-4000-8000-00000000a001")
DEMO_BALANCE_KZT = 50_000

log = structlog.get_logger()


@dataclass
class SeedResult:
    tenant_id: uuid.UUID
    products: int
    kb_chunks: int


def _load_products() -> list[dict[str, object]]:
    with (FIXTURES / "pion_products.csv").open(encoding="utf-8") as f:
        return [
            {
                "tenant_id": DEMO_TENANT_ID,
                "sku": row["sku"],
                "name": row["name"],
                "category": row["category"],
                "price": int(row["price"]),
                "stock": int(row["stock"]),
                "description": row["description"],
                "synonyms": row["synonyms"] or None,
            }
            for row in csv.DictReader(f)
        ]


def _load_kb() -> list[dict[str, object]]:
    items = json.loads((FIXTURES / "pion_kb.json").read_text(encoding="utf-8"))
    return [{"tenant_id": DEMO_TENANT_ID, "position": 0, **item} for item in items]


async def seed_demo() -> SeedResult:
    products, kb = _load_products(), _load_kb()

    async with tenant_session(DEMO_TENANT_ID) as session:
        tenant = {
            "id": DEMO_TENANT_ID,
            "name": "Цветы Пион",
            "niche": "цветы",
            "city": "Алматы",
            "status": "active",
        }
        await session.execute(
            insert(Tenant)
            .values(tenant)
            .on_conflict_do_update(index_elements=[Tenant.id], set_=tenant)
        )
        await session.execute(
            insert(BotProfile)
            .values(
                tenant_id=DEMO_TENANT_ID,
                version=1,
                is_active=True,
                tone="Тёплый и вежливый, на «вы», коротко и по делу.",
                greeting="Здравствуйте! Это «Цветы Пион». Подберём букет и доставим по Алматы.",
                rules={"handoff": "Если клиент просит индивидуальный заказ — позвать менеджера."},
            )
            .on_conflict_do_nothing(index_elements=[BotProfile.tenant_id, BotProfile.version])
        )

        stmt = insert(Product).values(products)
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_products_tenant_id_sku_norm",
                set_={
                    col: stmt.excluded[col]
                    for col in ("name", "category", "price", "stock", "description", "synonyms")
                },
            )
        )

        funded = await session.scalar(
            select(LedgerEntry.id).where(LedgerEntry.type == "topup").limit(1)
        )
        if funded is None:
            session.add(
                LedgerEntry(
                    tenant_id=DEMO_TENANT_ID,
                    type="topup",
                    amount_kzt=DEMO_BALANCE_KZT,
                    comment="демо-магазин",
                )
            )

        sources = [item["source"] for item in kb]
        await session.execute(delete(KbChunk).where(KbChunk.source.in_(sources)))
        await session.execute(insert(KbChunk).values(kb))

    return SeedResult(DEMO_TENANT_ID, len(products), len(kb))


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.env == "prod")
    from app.demo.service import ensure_demo_shop

    result = await seed_demo()
    queue = get_queue()
    await queue.enqueue(
        "reindex_embeddings", str(result.tenant_id), job_id=f"reindex:{result.tenant_id}"
    )
    await ensure_demo_shop(queue)
    log.info(
        "seed.done",
        tenant_id=str(result.tenant_id),
        products=result.products,
        kb_chunks=result.kb_chunks,
    )


if __name__ == "__main__":
    asyncio.run(main())
