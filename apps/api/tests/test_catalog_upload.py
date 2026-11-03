import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.storage import MemoryStorage
from tests.files import DIRTY_CATALOG, XLSX, csv_bytes, xlsx_bytes


async def test_upload_xlsx_creates_source_and_job(
    client: AsyncClient, owner: uuid.UUID, storage: MemoryStorage, owner_engine: AsyncEngine
) -> None:
    data = xlsx_bytes(DIRTY_CATALOG)
    response = await client.post("/catalog/uploads", files={"file": ("Прайс май.xlsx", data, XLSX)})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"

    async with owner_engine.connect() as conn:
        job = (
            await conn.execute(
                text(
                    "SELECT tenant_id, file_key, file_type, file_name "
                    "FROM ingest_jobs WHERE id = :id"
                ),
                {"id": body["id"]},
            )
        ).one()
        source_type = await conn.scalar(
            text("SELECT type FROM catalog_sources WHERE id = :id"), {"id": body["source_id"]}
        )
    assert job.tenant_id == owner
    assert job.file_type == "xlsx" and job.file_name == "Прайс май.xlsx"
    assert source_type == "excel"
    assert storage.objects[job.file_key][0] == data


async def test_upload_reuses_source(client: AsyncClient, owner: uuid.UUID) -> None:
    first = await client.post(
        "/catalog/uploads", files={"file": ("a.csv", csv_bytes([["name"], ["x"]]), "text/csv")}
    )
    source_id = first.json()["source_id"]
    second = await client.post(
        "/catalog/uploads",
        files={"file": ("b.csv", csv_bytes([["name"], ["y"]]), "text/csv")},
        data={"source_id": source_id},
    )
    assert second.json()["source_id"] == source_id
    assert second.json()["id"] != first.json()["id"]


async def test_upload_rejects_bad_files(client: AsyncClient, owner: uuid.UUID) -> None:
    wrong = await client.post("/catalog/uploads", files={"file": ("a.xls", b"old", "x")})
    assert wrong.status_code == 415

    settings = get_settings()
    limit = settings.catalog_max_upload_bytes
    settings.catalog_max_upload_bytes = 1000
    try:
        big = await client.post(
            "/catalog/uploads", files={"file": ("a.csv", b"x" * 2000, "text/csv")}
        )
    finally:
        settings.catalog_max_upload_bytes = limit
    assert big.status_code == 413

    foreign = await client.post(
        "/catalog/uploads",
        files={"file": ("a.csv", b"name\nx", "text/csv")},
        data={"source_id": str(uuid.uuid4())},
    )
    assert foreign.status_code == 404


async def test_upload_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/catalog/uploads", files={"file": ("a.csv", b"x", "text/csv")})
    assert response.status_code == 401
