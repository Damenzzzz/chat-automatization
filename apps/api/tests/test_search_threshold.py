import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.tools import product_item
from app.agent.understand import Understanding
from app.core.config import get_settings
from app.db.session import tenant_session
from app.llm.fake import FakeLLM
from app.search import search_kb, search_products
from app.search.types import ProductHit
from tests.agent_helpers import make_agent, make_conversation
from tests.fake_ml import FakeML, make_shop

CATALOG = [
    {"sku": "PN-001", "name": "Букет из 15 розовых пионов", "price": 32000},
    {"sku": "RS-101", "name": "Букет из 25 красных роз", "price": 24000},
]
KB = [
    {"source": "delivery", "title": "Доставка", "text": "Доставка по Алматы 2 000 ₸"},
    {"source": "payment", "title": "Оплата", "text": "Принимаем Kaspi и наличные"},
]


def hit(score: float | None, *, exact: bool = False) -> ProductHit:
    return ProductHit(
        id=uuid.uuid4(),
        sku="PN-001",
        name="Пионы",
        category=None,
        price=1,
        stock=1,
        reasons=("vector",),
        ranks={},
        rrf=0.0,
        score=score,
        exact=exact,
    )


def test_weak_needs_a_low_rerank_score() -> None:
    floor = get_settings().search_weak_score
    assert hit(floor / 2).weak
    assert not hit(floor).weak
    assert not hit(None).weak
    assert not hit(0.0, exact=True).weak
    assert product_item(hit(0.0))["weak"] is True
    assert "weak" not in product_item(hit(0.9))


async def test_search_marks_unrelated_products(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, CATALOG, kb=KB)
    async with tenant_session(tenant_id) as session:
        found = await search_products(session, "чехол айфон", ml=FakeML(), record=False)
        good = await search_products(session, "розовые пионы", ml=FakeML(), record=False)
    assert found.items and all(h.weak for h in found.items)
    assert good.items[0].sku == "PN-001"
    assert not good.items[0].weak


async def test_unrelated_kb_chunks_are_dropped(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, CATALOG, kb=KB)
    async with tenant_session(tenant_id) as session:
        none = await search_kb(session, "вакансии флориста", ml=FakeML(), record=False)
        some = await search_kb(session, "сколько стоит доставка", ml=FakeML(), record=False)
        offline = await search_kb(session, "доставка", ml=FakeML(fail=True), record=False)
    assert none.items == []
    assert [h.source for h in some.items] == ["delivery"]
    assert [(h.source, h.score) for h in offline.items] == [("delivery", None)]


async def test_weak_only_result_is_unanswered(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, CATALOG)
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    understood = Understanding(
        lang="ru", intent="product", complexity="low", search_query="чехол айфон"
    )
    llm = FakeLLM([understood, "Чехлов нет, могу предложить цветы."])
    agent, _ = await make_agent(llm)

    await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="Чехол на айфон?")

    prompt = llm.calls[1].messages[-1].text
    assert "[?]" in prompt
    assert "низкой уверенностью" in prompt
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM unanswered WHERE tenant_id = :t"), {"t": tenant_id}
        )
    assert count == 1
