from sqlalchemy import func, select, text

from app.db.session import tenant_session
from app.models import KbChunk, Product
from app.seed import DEMO_TENANT_ID, seed_demo


async def test_seed_is_idempotent(database: None) -> None:
    first = await seed_demo()
    second = await seed_demo()

    async with tenant_session(DEMO_TENANT_ID) as session:
        products = await session.scalar(select(func.count()).select_from(Product))
        kb = set((await session.scalars(select(KbChunk.source))).all())
        out_of_stock = await session.scalar(
            select(func.count()).select_from(Product).where(Product.stock == 0)
        )

    assert first == second
    assert products == first.products == 30
    assert kb == {"delivery", "payment", "schedule", "address"}
    assert out_of_stock and out_of_stock > 0


async def test_seed_is_searchable_in_russian_and_kazakh(database: None) -> None:
    await seed_demo()
    query = text(
        "SELECT sku FROM products WHERE tsv @@ websearch_to_tsquery(:cfg, :q) ORDER BY sku"
    )
    async with tenant_session(DEMO_TENANT_ID) as session:
        ru = (await session.scalars(query, {"cfg": "russian", "q": "тюльпаны"})).all()
        kk = (await session.scalars(query, {"cfg": "simple", "q": "қызғалдақ"})).all()
        sku = await session.scalar(select(Product.name).where(Product.sku_norm == "PN001"))

    assert ru == ["TL-201", "TL-202", "TL-203"]
    assert kk == ["TL-201", "TL-202", "TL-203"]
    assert sku == "Букет из 15 розовых пионов"
