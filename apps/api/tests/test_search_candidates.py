from collections.abc import Sequence

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import tenant_session
from app.search.candidates import fts_kb, fts_products, sku_codes, sku_products
from app.search.types import ProductFilters
from tests.fake_ml import make_shop

CATALOG = [
    {"sku": "PN-001", "name": "Букет из 15 розовых пионов", "category": "Пионы", "price": 32000},
    {"sku": "PN-002", "name": "Букет из 25 белых пионов", "category": "Пионы", "price": 52000},
    {"sku": "RS-101", "name": "Букет из 25 красных роз", "category": "Розы", "price": 24000},
    {"sku": "RS-103", "name": "Букет из 101 розы", "category": "Розы", "price": 89000},
    {"sku": "TL-201", "name": "Тюльпаны", "description": "Весенние тюльпаны", "price": 12500},
]


async def _names(engine: AsyncEngine, ids: Sequence[object]) -> list[str]:
    async with engine.connect() as conn:
        return [
            await conn.scalar(text("SELECT name FROM products WHERE id = :i"), {"i": i})
            for i in ids
        ]


@pytest.mark.parametrize(
    ("query", "codes"),
    [
        ("PN-001", ["PN001"]),
        ("есть pn 001?", ["PN001"]),
        ("артикул rs-101 в наличии", ["RS101"]),
        ("4870001234567", ["4870001234567"]),
        ("букет из 101 розы", []),
        ("пионы маме до 12к", []),
        ("бюджет 35000", []),
    ],
)
def test_sku_codes(query: str, codes: list[str]) -> None:
    assert sku_codes(query) == codes


async def test_fts_matches_any_word_with_stemming(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, CATALOG)
    async with tenant_session(tenant_id) as session:
        ids = await fts_products(session, tenant_id, "есть розовые пионы?", ProductFilters(), 50)
        typo = await fts_products(session, tenant_id, "тюльпан!", ProductFilters(), 50)
        empty = await fts_products(session, tenant_id, "и на в", ProductFilters(), 50)
    names = await _names(owner_engine, ids)
    assert names[0] == "Букет из 15 розовых пионов"
    assert set(names) == {"Букет из 15 розовых пионов", "Букет из 25 белых пионов"}
    assert await _names(owner_engine, typo) == ["Тюльпаны"]
    assert empty == []


async def test_fts_respects_filters(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, CATALOG)
    async with tenant_session(tenant_id) as session:
        ids = await fts_products(
            session, tenant_id, "букет пионов", ProductFilters(price_max=40000), 50
        )
    assert await _names(owner_engine, ids) == [
        "Букет из 15 розовых пионов",
        "Букет из 25 красных роз",
    ]


async def test_sku_exact_before_similar(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, CATALOG)
    async with tenant_session(tenant_id) as session:
        exact = await sku_products(session, tenant_id, ["RS101"], ProductFilters(), 50)
        fuzzy = await sku_products(session, tenant_id, ["RS10"], ProductFilters(), 50)
    assert exact[0][1] is True
    assert (await _names(owner_engine, [exact[0][0]])) == ["Букет из 25 красных роз"]
    assert fuzzy and not any(is_exact for _, is_exact in fuzzy)


async def test_fts_kb(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(
        owner_engine,
        [],
        kb=[
            {"source": "delivery", "title": "Доставка", "text": "Доставляем по Алматы"},
            {"source": "payment", "title": "Оплата", "text": "Kaspi QR и наличные"},
        ],
    )
    async with tenant_session(tenant_id) as session:
        ids = await fts_kb(session, tenant_id, "сколько стоит доставка", 10)
    assert len(ids) == 1
