import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.catalog.ingest import run_ingest
from app.core.config import get_settings
from app.core.storage import MemoryStorage
from tests.conftest import FakeSender, RecordingQueue, create_user, login
from tests.files import DIRTY_CATALOG, csv_bytes
from tests.test_catalog_ingest import MAPPING, _import


async def test_job_status_with_stats_and_row_errors(
    client: AsyncClient, owner: uuid.UUID, queue: RecordingQueue, storage: MemoryStorage
) -> None:
    job_id, _, _ = await _import(client, queue, storage, DIRTY_CATALOG)

    body = (await client.get(f"/ingest-jobs/{job_id}")).json()
    assert body["status"] == "done" and body["progress"] == 1.0
    assert (body["rows_total"], body["rows_done"]) == (9, 8)
    assert body["stats"] == {
        "created": 4,
        "updated": 0,
        "unchanged": 0,
        "skipped_empty": 1,
        "errors": 4,
    }
    assert {"row": 7, "reason": "цена не распознана: «договорная»"} in body["errors"]
    assert body["started_at"] and body["finished_at"]


async def test_pending_job_status(client: AsyncClient, owner: uuid.UUID) -> None:
    upload = await client.post(
        "/catalog/uploads",
        files={"file": ("a.csv", csv_bytes([["Название"], ["Пион"]]), "text/csv")},
    )
    body = (await client.get(f"/ingest-jobs/{upload.json()['id']}")).json()
    assert (body["status"], body["progress"], body["errors"]) == ("pending", None, [])


async def test_csv_cp1251_and_row_limit(
    client: AsyncClient, owner: uuid.UUID, queue: RecordingQueue, storage: MemoryStorage
) -> None:
    rows = [["Наименование", "Цена, тг"], ["Пион", "1 000"], ["Роза", "2 000"], ["Тюльпан", "500"]]
    data = csv_bytes(rows, delimiter=";", encoding="cp1251")
    upload = await client.post("/catalog/uploads", files={"file": ("p.csv", data, "text/csv")})
    job_id = upload.json()["id"]
    mapping = {k: v for k, v in MAPPING.items() if k in rows[0]}
    await client.post(f"/catalog/uploads/{job_id}/confirm", json={"mapping": mapping})

    settings = get_settings()
    limit, settings.catalog_max_rows = settings.catalog_max_rows, 2
    try:
        stats = await run_ingest(owner, uuid.UUID(job_id), storage)
    finally:
        settings.catalog_max_rows = limit

    assert (stats.created, stats.errors) == (2, 1)
    body = (await client.get(f"/ingest-jobs/{job_id}")).json()
    assert body["errors"] == [{"row": 4, "reason": "превышен лимит 2 строк, остальные пропущены"}]


async def test_broken_file_marks_job_failed(
    client: AsyncClient, owner: uuid.UUID, storage: MemoryStorage
) -> None:
    upload = await client.post(
        "/catalog/uploads", files={"file": ("p.xlsx", b"not a zip", "application/octet-stream")}
    )
    job_id = upload.json()["id"]
    await run_ingest(owner, uuid.UUID(job_id), storage)

    body = (await client.get(f"/ingest-jobs/{job_id}")).json()
    assert body["status"] == "failed"
    assert body["errors"][0]["row"] is None
    assert "bad_xlsx" in body["errors"][0]["reason"]


async def test_other_tenant_job_is_hidden(
    client: AsyncClient,
    owner: uuid.UUID,
    sender: FakeSender,
    owner_engine: AsyncEngine,
) -> None:
    upload = await client.post(
        "/catalog/uploads",
        files={"file": ("a.csv", csv_bytes([["Название"], ["Пион"]]), "text/csv")},
    )
    *_, other_phone = await create_user(owner_engine)
    await login(client, sender, other_phone)

    assert (await client.get(f"/ingest-jobs/{upload.json()['id']}")).status_code == 404
