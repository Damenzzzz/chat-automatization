from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import tenant_session
from app.search.candidates import enable_iterative_scan, vector_products
from app.search.types import ProductFilters
from tests.fake_ml import embed_text, make_shop


async def test_vector_candidates_ordered_by_similarity(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(
        owner_engine,
        [
            {"name": "Букет розовых пионов", "price": 30000},
            {"name": "Красные розы", "price": 20000},
            {"name": "Тюльпаны белые", "price": 10000},
        ],
    )
    async with tenant_session(tenant_id) as session:
        await enable_iterative_scan(session, 100)
        ids = await vector_products(
            session, tenant_id, embed_text("розовые пионы"), ProductFilters(), 50
        )
        names = [
            await session.scalar(text("SELECT name FROM products WHERE id = :i"), {"i": i})
            for i in ids
        ]
    assert len(ids) == 3
    assert names[0] == "Букет розовых пионов"


async def test_iterative_scan_fills_limit_under_selective_filter(
    owner_engine: AsyncEngine,
) -> None:
    products = [{"name": f"Букет пионов {i}", "price": 30000, "stock": 0} for i in range(200)]
    products += [{"name": f"Ромашки поле {i}", "price": 5000, "stock": 3} for i in range(12)]
    tenant_id = await make_shop(owner_engine, products)
    query, only_in_stock = embed_text("пионы"), ProductFilters(in_stock=True)
    async with tenant_session(tenant_id) as session:
        await enable_iterative_scan(session, 10)
        mode = await session.scalar(text("SELECT current_setting('hnsw.iterative_scan')"))
        ids = await vector_products(session, tenant_id, query, only_in_stock, 50)
    assert mode == "relaxed_order"
    assert len(ids) == 12


async def test_vector_candidates_isolated_by_tenant(owner_engine: AsyncEngine) -> None:
    mine = await make_shop(owner_engine, [{"name": "Пионы", "price": 1}])
    await make_shop(owner_engine, [{"name": "Пионы чужие", "price": 1}])
    async with tenant_session(mine) as session:
        ids = await vector_products(session, mine, embed_text("пионы"), ProductFilters(), 50)
    assert len(ids) == 1
