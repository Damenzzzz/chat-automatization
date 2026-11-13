import random
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.db.session import tenant_session
from app.search import ProductFilters, search_products
from app.search.fusion import rrf
from tests.fake_ml import FakeML, make_shop

FLOWERS = ["пионы", "розы", "тюльпаны", "ромашки", "хризантемы", "гортензии"]
COLORS = ["розовые", "белые", "красные", "жёлтые"]


def _catalog(seed: int = 7) -> list[dict[str, object]]:
    rng = random.Random(seed)  # noqa: S311
    items: list[dict[str, object]] = []
    for i in range(60):
        flower, color = rng.choice(FLOWERS), rng.choice(COLORS)
        items.append(
            {
                "sku": f"FL-{i:03d}",
                "name": f"Букет {color} {flower} {i}",
                "category": flower.capitalize(),
                "description": f"{color.capitalize()} {flower} в упаковке",
                "price": rng.randrange(3000, 90000, 500),
                "stock": rng.choice([0, 0, 1, 5, 12]),
            }
        )
    return items


@pytest.fixture
async def shop(owner_engine: AsyncEngine) -> uuid.UUID:
    return await make_shop(owner_engine, _catalog())


def test_rrf_sums_reciprocal_ranks() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = rrf({"vector": [a, b], "fts": [b, c]}, k=60)
    assert [f.id for f in fused] == [b, a, c]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[0].ranks == {"vector": 2, "fts": 1}


@pytest.mark.parametrize("budget", [3000, 5000, 12000, 25000, 40000])
@pytest.mark.parametrize("query", ["розовые пионы", "букет", "что-нибудь маме", "FL-010"])
async def test_price_filter_never_exceeds_budget(shop: uuid.UUID, query: str, budget: int) -> None:
    async with tenant_session(shop) as session:
        result = await search_products(
            session, query, ProductFilters(price_max=budget), ml=FakeML(), limit=10
        )
    assert all(hit.price is not None and hit.price <= budget for hit in result.items)


async def test_price_range(shop: uuid.UUID) -> None:
    async with tenant_session(shop) as session:
        result = await search_products(
            session, "букет", ProductFilters(price_min=20000, price_max=30000), ml=FakeML()
        )
    assert result.items
    assert all(20000 <= (hit.price or 0) <= 30000 for hit in result.items)


@pytest.mark.parametrize("query", ["белые розы", "тюльпаны", "букет"])
async def test_in_stock_excludes_zero_stock(shop: uuid.UUID, query: str) -> None:
    async with tenant_session(shop) as session:
        everything = await search_products(session, query, ml=FakeML(), limit=50)
        available = await search_products(
            session, query, ProductFilters(in_stock=True), ml=FakeML(), limit=50
        )
    assert any(hit.stock == 0 for hit in everything.items)
    assert available.items
    assert all(hit.stock != 0 for hit in available.items)


async def test_category_filter(shop: uuid.UUID) -> None:
    async with tenant_session(shop) as session:
        result = await search_products(
            session, "букет", ProductFilters(category="розы"), ml=FakeML(), limit=50
        )
    assert result.items
    assert {hit.category for hit in result.items} == {"Розы"}


@pytest.mark.parametrize("query", ["FL-042", "fl042", "есть артикул FL 042?", "FL-042 красный"])
async def test_sku_query_finds_product_first(shop: uuid.UUID, query: str) -> None:
    async with tenant_session(shop) as session:
        result = await search_products(session, query, ml=FakeML())
    assert result.items[0].sku == "FL-042"
    assert "sku" in result.items[0].reasons


async def test_search_works_without_ml(shop: uuid.UUID) -> None:
    async with tenant_session(shop) as session:
        result = await search_products(session, "розовые пионы", ml=FakeML(fail=True))
    assert result.items
    assert "vector" not in result.candidates
    assert all("vector" not in hit.reasons for hit in result.items)


async def test_hits_carry_reasons_and_db_price(shop: uuid.UUID) -> None:
    async with tenant_session(shop) as session:
        result = await search_products(session, "розовые пионы", ml=FakeML())
    top = result.items[0]
    assert set(top.reasons) <= {"vector", "fts", "sku"}
    assert top.reasons
    assert set(top.ranks) == set(top.reasons)
    assert isinstance(top.price, int)


class ScriptedML(FakeML):
    def __init__(self, prefer: str) -> None:
        super().__init__()
        self.prefer = prefer

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        self.reranked.append(documents)
        return [1.0 if self.prefer in d else 0.1 for d in documents]


async def test_reranker_reorders_top_and_limits_pool(owner_engine: AsyncEngine) -> None:
    class ReverseML(FakeML):
        async def rerank(self, query: str, documents: list[str]) -> list[float]:
            self.reranked.append(documents)
            return [i / len(documents) for i in range(len(documents))]

    tenant_id = await make_shop(
        owner_engine, [{"name": f"Букет пионов {i}", "price": 10000 + i} for i in range(40)]
    )
    ml = ReverseML()
    async with tenant_session(tenant_id) as session:
        result = await search_products(session, "букет пионов", ml=ml)
    [pool] = ml.reranked
    assert len(pool) == 30
    assert [h.name for h in result.items] == [d.split("\n")[0] for d in pool[::-1][:5]]
    assert [h.score for h in result.items] == sorted(
        (h.score or 0 for h in result.items), reverse=True
    )


async def test_exact_sku_stays_first_after_rerank(shop: uuid.UUID) -> None:
    async with tenant_session(shop) as session:
        result = await search_products(session, "FL-042 белые розы", ml=ScriptedML("розы"))
    assert result.items[0].sku == "FL-042"


async def test_rerank_failure_falls_back_to_rrf(shop: uuid.UUID) -> None:
    class RerankDown(FakeML):
        async def rerank(self, query: str, documents: list[str]) -> list[float]:
            from app.mlclient import MLError

            raise MLError("down")

    async with tenant_session(shop) as session:
        result = await search_products(session, "розовые пионы", ml=RerankDown())
        plain = await search_products(session, "розовые пионы", ml=FakeML(), use_reranker=False)
    assert [h.id for h in result.items] == [h.id for h in plain.items]
    assert all(h.score is None for h in result.items)


async def test_exact_sku_survives_a_small_rerank_pool(
    shop: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    wanted = _catalog()[42]
    flower = next(f for f in FLOWERS if f.capitalize() != wanted["category"])
    color = next(c for c in COLORS if c not in str(wanted["name"]))
    monkeypatch.setattr(get_settings(), "search_rerank_top", 3)
    async with tenant_session(shop) as session:
        result = await search_products(
            session, f"FL-042 {color} {flower} букет в упаковке", ml=FakeML(), record=False
        )
    assert result.items[0].sku == "FL-042"
