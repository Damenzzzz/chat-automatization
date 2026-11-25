import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.nodes import AgentDeps, AgentNodes
from app.agent.tools import merge_context
from app.agent.understand import Understanding
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation, nodes
from tests.conftest import RecordingQueue
from tests.fake_ml import FakeML, make_shop

CATALOG = [
    {"sku": "PN-001", "name": "Букет из 15 розовых пионов", "price": 32000, "stock": 6},
    {"sku": "RS-101", "name": "Букет из 25 красных роз", "price": 24000, "stock": 3},
]


def understood(intent: str, *, follow_up: bool = False, query: str | None = None) -> Understanding:
    return Understanding(
        lang="ru", intent=intent, complexity="low", follow_up=follow_up, search_query=query
    )


@pytest.fixture
async def shop(owner_engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await make_shop(owner_engine, CATALOG)
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    return tenant_id, conversation_id


async def _unanswered(engine: AsyncEngine, tenant_id: uuid.UUID) -> int:
    async with engine.connect() as conn:
        value: int = await conn.scalar(
            text("SELECT count(*) FROM unanswered WHERE tenant_id = :t"), {"t": tenant_id}
        )
    return value


async def test_follow_up_price_passes_check_with_fresh_price(
    shop: tuple[uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    llm = FakeLLM(
        [
            understood("product", query="розовые пионы"),
            "Есть «Букет из 15 розовых пионов» за 32 000 ₸.",
            understood("smalltalk", follow_up=True),
            "Он стоит 35 000 ₸, в наличии 6 шт.",
        ]
    )
    agent, _ = await make_agent(llm)
    await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="Есть розовые пионы?")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE products SET price = 35000 WHERE tenant_id = :t AND sku = 'PN-001'"),
            {"t": shop[0]},
        )

    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="А он сколько?")

    assert result.reply == "Он стоит 35 000 ₸, в наличии 6 шт."
    assert "fallback" not in nodes(result.trace)
    prompt = llm.calls[3].messages[-1].text
    assert "Товары, о которых уже говорили в диалоге" in prompt
    assert "PN-001 «Букет из 15 розовых пионов» — 35 000 ₸" in prompt
    assert await _unanswered(owner_engine, shop[0]) == 0


async def test_old_price_from_history_is_rejected(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    llm = FakeLLM(
        [
            understood("product", query="розовые пионы"),
            "Есть «Букет из 15 розовых пионов» за 32 000 ₸.",
            understood("smalltalk", follow_up=True),
            "Он стоит 30 000 ₸.",
            "Он стоит 32 000 ₸.",
        ]
    )
    agent, _ = await make_agent(llm)
    await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="Есть розовые пионы?")
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="А он сколько?")

    assert nodes(result.trace).count("guard_out") == 2
    assert result.reply == "Он стоит 32 000 ₸."


async def test_removed_product_is_forgotten(
    shop: tuple[uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    llm = FakeLLM(
        [
            understood("product", query="розовые пионы"),
            "Есть «Букет из 15 розовых пионов» за 32 000 ₸.",
            understood("smalltalk", follow_up=True),
            "Уточню у менеджера.",
        ]
    )
    agent, _ = await make_agent(llm)
    await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="Есть розовые пионы?")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE products SET is_active = false WHERE tenant_id = :t"), {"t": shop[0]}
        )

    await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="А он сколько?")

    assert "уже говорили" not in llm.calls[3].messages[-1].text
    state = await agent.graph.aget_state({"configurable": {"thread_id": str(shop[1])}})
    assert state.values["recent_products"] == []


def test_remembered_prefers_mentioned_products() -> None:
    agent = AgentNodes(AgentDeps(llm=None, ml=FakeML(), queue=RecordingQueue()))
    context = [
        {"type": "product", "id": "a", "name": "Пионы", "sku": "PN-1"},
        {"type": "product", "id": "b", "name": "Розы", "sku": "RS-1"},
        {"type": "product", "id": "c", "name": "Тюльпаны", "sku": "TL-1", "recent": True},
    ]
    state = {"reply": "Розы есть", "context": context, "recent_products": ["c", "z"]}
    assert agent.remembered(state) == ["b", "c", "z"]  # type: ignore[arg-type]

    nothing = {**state, "reply": "Посмотрите варианты", "intent": "product"}
    assert agent.remembered(nothing) == ["a", "b", "c", "z"]  # type: ignore[arg-type]
    many = {**state, "recent_products": [str(i) for i in range(20)]}
    assert len(agent.remembered(many)) == 8  # type: ignore[arg-type]


def test_search_hit_replaces_recent_copy() -> None:
    recent = [{"type": "product", "id": "a", "price": 1, "recent": True}]
    merged = merge_context(recent, [{"type": "product", "id": "a", "price": 2}])
    assert merged == [{"type": "product", "id": "a", "price": 2}]
    kept = merge_context(merged, [{"type": "product", "id": "a", "price": 3, "recent": True}])
    assert kept == merged
