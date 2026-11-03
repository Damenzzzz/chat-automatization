import copy
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.catalog.ingest import run_ingest
from app.core.storage import MemoryStorage
from tests.conftest import RecordingQueue
from tests.files import DIRTY_CATALOG, XLSX, xlsx_bytes

MAPPING = {
    "Артикул": "sku",
    "Наименование": "name",
    "Цена, тг": "price",
    "Остаток": "stock",
    "Категория": "category",
    "Описание": "description",
    "Фото": "image_url",
    "Цвет": "attributes.цвет",
}


async def _import(
    client: AsyncClient,
    queue: RecordingQueue,
    storage: MemoryStorage,
    rows: list[list[Any]],
    source_id: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    upload = await client.post(
        "/catalog/uploads",
        files={"file": ("price.xlsx", xlsx_bytes(rows), XLSX)},
        data={"source_id": source_id} if source_id else {},
    )
    job_id, source_id = upload.json()["id"], upload.json()["source_id"]
    confirm = await client.post(f"/catalog/uploads/{job_id}/confirm", json={"mapping": MAPPING})
    assert confirm.status_code == 202, confirm.text

    function, (tenant_id, queued_job) = queue.jobs[-1]
    assert function == "ingest_catalog" and queued_job == job_id
    stats = await run_ingest(uuid.UUID(str(tenant_id)), uuid.UUID(job_id), storage)
    return job_id, source_id, vars(stats)


async def _products(engine: AsyncEngine, tenant_id: uuid.UUID) -> dict[str, Any]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT coalesce(sku_norm, name) AS key, * FROM products "
                "WHERE tenant_id = :t ORDER BY key"
            ),
            {"t": tenant_id},
        )
        return {r.key: r for r in rows}


async def test_dirty_xlsx_import(
    client: AsyncClient,
    owner: uuid.UUID,
    queue: RecordingQueue,
    storage: MemoryStorage,
    owner_engine: AsyncEngine,
) -> None:
    job_id, source_id, stats = await _import(client, queue, storage, DIRTY_CATALOG)

    assert stats == {"created": 4, "updated": 0, "unchanged": 0, "skipped_empty": 1, "errors": 4}
    products = await _products(owner_engine, owner)
    assert set(products) == {"PN001", "PN002", "RS101", "Открытка"}

    pion = products["PN001"]
    assert (pion.price, pion.stock, pion.description) == (32000, 6, "Розовые пионы")
    assert pion.attributes == {"цвет": "розовый"} and pion.images == ["https://img/1.jpg"]
    assert pion.embedding_stale is True and len(pion.content_hash) == 64
    assert (products["PN002"].price, products["PN002"].stock) == (52000, 3)
    assert len(products["RS101"].images) == 2
    card = products["Открытка"]
    assert (card.sku, card.price, card.stock, card.name_hash is not None) == (None, 1500, 0, True)

    async with owner_engine.connect() as conn:
        job = (
            await conn.execute(text("SELECT * FROM ingest_jobs WHERE id = :id"), {"id": job_id})
        ).one()
        column_map = await conn.scalar(
            text("SELECT column_map FROM catalog_sources WHERE id = :id"), {"id": source_id}
        )
    assert (job.status, job.rows_done, job.rows_total) == ("done", 8, 9)
    assert {e["row"]: e["reason"] for e in job.errors} == {
        6: "дубль артикула «PN-001», уже был в строке 2",
        7: "цена не распознана: «договорная»",
        9: "нет названия",
        10: "отрицательный остаток: «-2»",
    }
    assert column_map == MAPPING


async def test_reimport_same_file_changes_nothing(
    client: AsyncClient,
    owner: uuid.UUID,
    queue: RecordingQueue,
    storage: MemoryStorage,
    owner_engine: AsyncEngine,
) -> None:
    _, source_id, _ = await _import(client, queue, storage, DIRTY_CATALOG)
    before = await _products(owner_engine, owner)

    _, _, stats = await _import(client, queue, storage, DIRTY_CATALOG, source_id)

    assert stats["created"] == 0 and stats["updated"] == 0 and stats["unchanged"] == 4
    after = await _products(owner_engine, owner)
    assert {k: r.updated_at for k, r in after.items()} == {
        k: r.updated_at for k, r in before.items()
    }


async def test_price_change_keeps_embedding_fresh(
    client: AsyncClient,
    owner: uuid.UUID,
    queue: RecordingQueue,
    storage: MemoryStorage,
    owner_engine: AsyncEngine,
) -> None:
    _, source_id, _ = await _import(client, queue, storage, DIRTY_CATALOG)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE products SET embedding_stale = false WHERE tenant_id = :t"), {"t": owner}
        )

    rows = copy.deepcopy(DIRTY_CATALOG)
    rows[1][2], rows[1][3] = "35 000 тг", "2"
    rows[4][5] = "Розы Freedom 70 см"
    _, _, stats = await _import(client, queue, storage, rows, source_id)

    assert stats["updated"] == 2 and stats["unchanged"] == 2
    products = await _products(owner_engine, owner)
    assert (products["PN001"].price, products["PN001"].stock) == (35000, 2)
    assert products["PN001"].embedding_stale is False
    assert products["RS101"].embedding_stale is True
    assert products["PN002"].embedding_stale is False


@pytest.mark.parametrize(
    ("mapping", "problem"),
    [
        ({"Артикул": "sku"}, "нужна колонка с названием товара (name)"),
        ({"Наименование": "name", "Цвет": "colour"}, "неизвестное поле «colour»"),
        ({"Наименование": "name", "Описание": "name"}, "поле name назначено нескольким колонкам"),
        ({"Наименование": "name", "Нет такой": "sku"}, "нет колонки «Нет такой»"),
    ],
)
async def test_confirm_validates_mapping(
    client: AsyncClient,
    owner: uuid.UUID,
    queue: RecordingQueue,
    mapping: dict[str, str],
    problem: str,
) -> None:
    upload = await client.post(
        "/catalog/uploads", files={"file": ("p.xlsx", xlsx_bytes(DIRTY_CATALOG), XLSX)}
    )
    response = await client.post(
        f"/catalog/uploads/{upload.json()['id']}/confirm", json={"mapping": mapping}
    )
    assert response.status_code == 422
    assert problem in response.json()["detail"]
    assert queue.jobs == []
