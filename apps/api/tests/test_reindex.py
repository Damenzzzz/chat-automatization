import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app import worker
from app.catalog.embedding_text import product_text
from app.catalog.reindex import reindex_tenant, tenants_needing_reindex
from app.core.storage import MemoryStorage
from tests.conftest import RecordingQueue
from tests.files import DIRTY_CATALOG, XLSX, xlsx_bytes
from tests.test_catalog_ingest import MAPPING


class FakeML:
    def __init__(self, on_embed: Any = None) -> None:
        self.texts: list[str] = []
        self.on_embed = on_embed

    async def embed(self, texts: list[str], kind: Any) -> list[list[float]]:
        assert kind == "document"
        self.texts.extend(texts)
        if self.on_embed:
            await self.on_embed()
        return [[1.0] + [0.0] * 1023 for _ in texts]


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str | None]] = []

    async def enqueue_job(self, name: str, *args: Any, _job_id: str | None = None) -> None:
        self.jobs.append((name, args, _job_id))


async def _shop(engine: AsyncEngine, products: int = 70) -> uuid.UUID:
    async with engine.begin() as conn:
        tenant_id: uuid.UUID = await conn.scalar(
            text("INSERT INTO tenants (name) VALUES ('ML') RETURNING id")
        )
        for i in range(products):
            await conn.execute(
                text(
                    "INSERT INTO products (tenant_id, sku, name, price, stock, category, synonyms) "
                    "VALUES (:t, :sku, :name, 32000, 5, 'Пионы', 'пион гүлдері')"
                ),
                {"t": tenant_id, "sku": f"P-{i:03d}", "name": f"Букет пионов №{i}"},
            )
        for source in ("delivery", "payment"):
            await conn.execute(
                text(
                    "INSERT INTO kb_chunks (tenant_id, source, title, text) "
                    "VALUES (:t, :s, :s, 'x')"
                ),
                {"t": tenant_id, "s": source},
            )
    return tenant_id


async def _stale(engine: AsyncEngine, tenant_id: uuid.UUID) -> int:
    async with engine.connect() as conn:
        count: int = await conn.scalar(
            text(
                "SELECT (SELECT count(*) FROM products WHERE tenant_id = :t AND "
                "(embedding_stale OR embedding IS NULL)) + (SELECT count(*) FROM kb_chunks "
                "WHERE tenant_id = :t AND (embedding_stale OR embedding IS NULL))"
            ),
            {"t": tenant_id},
        )
        return count


def test_product_text_excludes_price_and_stock() -> None:
    value = product_text(
        "Букет из 15 пионов", "Пионы", "Розовые пионы", {"цвет": "розовый"}, "пион гүлдері"
    )
    assert value == (
        "Букет из 15 пионов\nКатегория: Пионы\nРозовые пионы\nцвет: розовый\nСинонимы: пион гүлдері"
    )
    assert "32000" not in value and "₸" not in value


async def test_reindex_once_then_nothing(owner_engine: AsyncEngine) -> None:
    tenant_id = await _shop(owner_engine)
    assert tenant_id in await tenants_needing_reindex()

    ml = FakeML()
    stats = await reindex_tenant(tenant_id, ml)

    assert (stats.products, stats.kb_chunks, stats.skipped) == (70, 2, 0)
    assert len(ml.texts) == 72
    assert all("32000" not in t for t in ml.texts)
    assert await _stale(owner_engine, tenant_id) == 0
    async with owner_engine.connect() as conn:
        dims = await conn.scalar(
            text("SELECT DISTINCT vector_dims(embedding) FROM products WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    assert dims == 1024
    assert tenant_id not in await tenants_needing_reindex()

    again = FakeML()
    assert vars(await reindex_tenant(tenant_id, again)) == {
        "products": 0,
        "kb_chunks": 0,
        "skipped": 0,
    }
    assert again.texts == []


async def test_only_changed_products_are_reembedded(owner_engine: AsyncEngine) -> None:
    tenant_id = await _shop(owner_engine, products=5)
    await reindex_tenant(tenant_id, FakeML())

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE products SET price = 1 WHERE tenant_id = :t"), {"t": tenant_id}
        )
        await conn.execute(
            text(
                "UPDATE products SET description = 'Новое описание', embedding_stale = true "
                "WHERE tenant_id = :t AND sku = 'P-002'"
            ),
            {"t": tenant_id},
        )

    ml = FakeML()
    stats = await reindex_tenant(tenant_id, ml)
    assert stats.products == 1
    assert ml.texts == ["Букет пионов №2\nКатегория: Пионы\nНовое описание\nСинонимы: пион гүлдері"]


async def test_concurrent_edit_keeps_row_stale(owner_engine: AsyncEngine) -> None:
    tenant_id = await _shop(owner_engine, products=2)

    async def edit_during_embed() -> None:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE products SET description = 'изменили', embedding_stale = true "
                    "WHERE tenant_id = :t AND sku = 'P-000'"
                ),
                {"t": tenant_id},
            )

    stats = await reindex_tenant(tenant_id, FakeML(on_embed=edit_during_embed))
    assert (stats.products, stats.skipped) == (1, 1)
    assert await _stale(owner_engine, tenant_id) == 1


async def test_reindex_all_enqueues_per_tenant(owner_engine: AsyncEngine) -> None:
    tenant_id = await _shop(owner_engine, products=1)
    redis = FakeRedis()

    count = await worker.reindex_all({"redis": redis})

    assert count >= 1
    assert (worker.REINDEX, (str(tenant_id),), f"reindex:{tenant_id}") in redis.jobs


async def test_ingest_triggers_reindex(
    client: AsyncClient,
    owner: uuid.UUID,
    queue: RecordingQueue,
    storage: MemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = await client.post(
        "/catalog/uploads", files={"file": ("p.xlsx", xlsx_bytes(DIRTY_CATALOG), XLSX)}
    )
    job_id = upload.json()["id"]
    await client.post(f"/catalog/uploads/{job_id}/confirm", json={"mapping": MAPPING})
    monkeypatch.setattr(worker, "get_storage", lambda: storage)
    redis = FakeRedis()

    await worker.ingest_catalog({"redis": redis}, str(owner), job_id)
    assert redis.jobs == [(worker.REINDEX, (str(owner),), f"reindex:{owner}")]

    redis.jobs.clear()
    upload = await client.post(
        "/catalog/uploads",
        files={"file": ("p.xlsx", xlsx_bytes(DIRTY_CATALOG), XLSX)},
        data={"source_id": upload.json()["source_id"]},
    )
    await client.post(f"/catalog/uploads/{upload.json()['id']}/confirm", json={"mapping": MAPPING})
    await worker.ingest_catalog({"redis": redis}, str(owner), upload.json()["id"])
    assert redis.jobs == []
