import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation, nodes
from tests.fake_ml import make_shop

CATALOG = [{"sku": "PN-001", "name": "Букет из 15 розовых пионов", "price": 32000, "stock": 6}]
KB = [{"source": "delivery", "title": "Доставка", "text": "Доставка в Каскелен 3 000 ₸"}]


@pytest.fixture
async def shop(owner_engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await make_shop(owner_engine, CATALOG, kb=KB)
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    return tenant_id, conversation_id


def understood(intent: str, kb_query: str | None) -> Understanding:
    return Understanding(
        lang="ru", intent=intent, complexity="low", search_query="пионы", kb_query=kb_query
    )


async def test_product_and_delivery_in_one_message(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    reply = "Пионы есть за 32 000 ₸, доставка в Каскелен 3 000 ₸, итого 35 000 ₸."
    llm = FakeLLM([understood("product", "доставка в Каскелен"), reply])
    agent, _ = await make_agent(llm)

    result = await agent.run(
        tenant_id=shop[0], conversation_id=shop[1], text="Есть пионы? И доставляете в Каскелен?"
    )

    path = nodes(result.trace)
    assert path.index("retrieve") < path.index("kb") < path.index("respond")
    kb_step = next(t for t in result.trace if t["node"] == "kb")
    assert kb_step["query"] == "доставка в Каскелен"
    prompt = llm.calls[1].messages[-1].text
    assert "PN-001" in prompt
    assert "Доставка в Каскелен 3 000 ₸" in prompt
    assert result.reply == reply


async def test_order_with_question_also_reads_kb(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    llm = FakeLLM([understood("order", "оплата Kaspi"), "Оформим, Kaspi принимаем."])
    agent, _ = await make_agent(llm)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="Беру, можно Kaspi?")
    assert "kb" in nodes(result.trace)


async def test_plain_product_question_skips_kb(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    llm = FakeLLM([understood("product", None), "Пионы есть за 32 000 ₸."])
    agent, _ = await make_agent(llm)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="Есть пионы?")
    assert "kb" not in nodes(result.trace)


async def test_missing_condition_is_marked_unanswered(
    shop: tuple[uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM kb_chunks WHERE tenant_id = :t"), {"t": shop[0]})
    llm = FakeLLM([understood("product", "возврат"), "Пионы за 32 000 ₸, про возврат уточню."])
    agent, _ = await make_agent(llm)

    await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="Пионы есть? Возврат можно?")

    assert "В базе знаний нет ответа" in llm.calls[1].messages[-1].text
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM unanswered WHERE tenant_id = :t"), {"t": shop[0]}
        )
    assert count == 1
