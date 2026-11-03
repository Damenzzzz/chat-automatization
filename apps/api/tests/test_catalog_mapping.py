import uuid

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.catalog.mapping import heuristic_mapping
from app.catalog.reader import open_table, preview
from tests.files import DIRTY_CATALOG, XLSX, csv_bytes, xlsx_bytes


def _fields(
    headers: list[str], saved: dict[str, str | None] | None = None
) -> dict[str, str | None]:
    proposal = heuristic_mapping(headers, [], saved)
    return {c.column: c.field for c in proposal.columns}


def test_heuristic_synonyms() -> None:
    assert _fields(DIRTY_CATALOG[0]) == {
        "Артикул": "sku",
        "Наименование": "name",
        "Цена, тг": "price",
        "Остаток": "stock",
        "Категория": "category",
        "Описание": "description",
        "Фото": "image_url",
        "Цвет": "attributes.цвет",
    }
    assert _fields(["№", "Товар", "Стоимость", "Кол-во", "Наличие"]) == {
        "№": None,
        "Товар": "name",
        "Стоимость": "price",
        "Кол-во": "stock",
        "Наличие": "attributes.наличие",
    }


def test_each_base_field_used_once() -> None:
    proposal = heuristic_mapping(["Название", "Цена опт", "Цена розница"], [])
    by_column = {c.column: (c.field, c.confidence) for c in proposal.columns}
    assert by_column["Цена розница"] == ("price", 0.95)
    assert by_column["Цена опт"][0] == "attributes.цена опт"


def test_saved_mapping_wins() -> None:
    saved = {"Наименование": "name", "Код": None, "Прайс": "price"}
    proposal = heuristic_mapping(["Наименование", "Код", "Прайс"], [], saved)
    assert proposal.method == "saved"
    assert {c.column: c.field for c in proposal.columns} == saved
    assert all(c.confidence == 1.0 for c in proposal.columns)


def test_reader_skips_title_rows_and_detects_csv_dialect() -> None:
    data = csv_bytes([["Прайс на май"], [], ["Название", "Цена"], ["Пион", "100"]], delimiter=";")
    table = open_table(data, "csv")
    assert table.headers == ["Прайс на май"]

    data = csv_bytes(
        [["Название", "Цена", "Цена"], ["Пион", "100", "90"]], delimiter=";", encoding="cp1251"
    )
    headers, rows = preview(data, "csv")
    assert headers == ["Название", "Цена", "Цена (2)"]
    assert rows == [["Пион", "100", "90"]]


def test_reader_xlsx_preview_skips_empty_rows() -> None:
    headers, rows = preview(xlsx_bytes(DIRTY_CATALOG), "xlsx")
    assert headers[1] == "Наименование"
    assert len(rows) == 5
    assert all(any(v not in (None, "") for v in r) for r in rows)


async def test_mapping_endpoint(
    client: AsyncClient, owner: uuid.UUID, owner_engine: AsyncEngine
) -> None:
    upload = await client.post(
        "/catalog/uploads", files={"file": ("p.xlsx", xlsx_bytes(DIRTY_CATALOG), XLSX)}
    )
    job_id = upload.json()["id"]

    response = await client.get(f"/catalog/uploads/{job_id}/mapping")
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "heuristic"
    price = next(c for c in body["columns"] if c["column"] == "Цена, тг")
    assert price["field"] == "price" and price["confidence"] == 0.95
    assert price["samples"][:2] == ["32 000 тг", "52 000,00 ₸"]

    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE catalog_sources SET column_map = :m WHERE id = :id"),
            {"m": '{"Цвет": "attributes.color"}', "id": upload.json()["source_id"]},
        )
    body = (await client.get(f"/catalog/uploads/{job_id}/mapping")).json()
    color = next(c for c in body["columns"] if c["column"] == "Цвет")
    assert color == {**color, "field": "attributes.color", "confidence": 1.0}

    assert (await client.get(f"/catalog/uploads/{uuid.uuid4()}/mapping")).status_code == 404
