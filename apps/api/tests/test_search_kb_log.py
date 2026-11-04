import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import tenant_session
from app.search import ProductFilters, search_kb, search_products
from app.search.lang import detect_lang
from tests.fake_ml import FakeML, make_shop

KB = [
    {"source": "delivery", "title": "Доставка", "text": "Доставляем по Алматы, доставка 2000 ₸"},
    {"source": "payment", "title": "Оплата", "text": "Kaspi QR, перевод, наличные курьеру"},
    {"source": "schedule", "title": "График работы", "text": "Работаем ежедневно с 8 до 22"},
    {"source": "address", "title": "Адрес", "text": "Алматы, Жибек Жолы 115, самовывоз"},
]


@pytest.mark.parametrize(
    ("query", "lang"),
    [
        ("есть розовые пионы?", "ru"),
        ("қызыл раушан гүлдері бар ма?", "kk"),
        ("анама гүл керек", "kk"),
        ("пион гүлі", "mixed"),
        ("PN-001", None),
    ],
)
def test_detect_lang(query: str, lang: str | None) -> None:
    assert detect_lang(query) == lang


async def test_search_kb_top3(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, [], kb=KB)
    async with tenant_session(tenant_id) as session:
        result = await search_kb(session, "сколько стоит доставка по Алматы", ml=FakeML())
    assert len(result.items) == 3
    assert result.items[0].source == "delivery"
    assert set(result.items[0].reasons) == {"vector", "fts"}


async def _logs(engine: AsyncEngine, tenant_id: uuid.UUID) -> list[dict[str, object]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT kind, query, lang, result_count, has_in_stock, filters, results,"
                " latency_ms FROM search_log WHERE tenant_id = :t ORDER BY created_at"
            ),
            {"t": tenant_id},
        )
        return [dict(r._mapping) for r in rows]


async def test_searches_are_logged(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(
        owner_engine,
        [
            {"sku": "PN-1", "name": "Розовые пионы", "price": 30000, "stock": 0},
            {"sku": "RS-1", "name": "Красные розы", "price": 20000, "stock": 4},
        ],
        kb=KB,
    )
    async with tenant_session(tenant_id) as session:
        await search_products(session, "пионы", ProductFilters(price_max=35000), ml=FakeML())
        await search_products(session, "пион гүлі", ProductFilters(in_stock=True), ml=FakeML())
        await search_products(session, "тюльпаны", ProductFilters(price_max=100), ml=FakeML())
        await search_kb(session, "доставка", ml=FakeML())
        await search_products(session, "без журнала", ml=FakeML(), record=False)

    logs = await _logs(owner_engine, tenant_id)
    assert [row["kind"] for row in logs] == ["product", "product", "product", "kb"]
    first, mixed, empty, kb = logs
    assert first["lang"] == "ru"
    assert first["filters"] == {"price_max": 35000}
    assert first["result_count"] == len(first["results"]) > 0  # type: ignore[arg-type]
    assert mixed["lang"] == "mixed"
    assert empty["result_count"] == 0
    assert empty["has_in_stock"] is False
    assert kb["result_count"] == 3
    assert kb["has_in_stock"] is None
    assert all(isinstance(row["latency_ms"], int) for row in logs)


async def test_has_in_stock_reflects_found_products(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(
        owner_engine,
        [{"sku": "PN-1", "name": "Розовые пионы", "price": 30000, "stock": 0}],
    )
    async with tenant_session(tenant_id) as session:
        await search_products(session, "PN-1", ml=FakeML())
        await session.execute(text("UPDATE products SET stock = 3"))
        await search_products(session, "PN-1", ml=FakeML())
    logs = await _logs(owner_engine, tenant_id)
    assert [row["has_in_stock"] for row in logs] == [False, True]
