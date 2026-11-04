import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.llm import LLMResponse, Usage
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation
from tests.fake_ml import make_shop


async def _messages(engine: AsyncEngine, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT role, content, model, tokens_in, tokens_out, cached_tokens, cost_usd,"
                " latency_ms, trace FROM messages WHERE conversation_id = :c ORDER BY created_at"
            ),
            {"c": conversation_id},
        )
        return [dict(r._mapping) for r in rows]


async def _unanswered(engine: AsyncEngine, tenant_id: uuid.UUID) -> list[tuple[str, str]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT question, answer FROM unanswered WHERE tenant_id = :t"), {"t": tenant_id}
        )
        return [(r.question, r.answer) for r in rows]


def understood(intent: str) -> Understanding:
    return Understanding(lang="ru", intent=intent, complexity="low")


async def test_turn_writes_usage_cost_and_trace(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(
        owner_engine, [{"sku": "PN-001", "name": "Розовые пионы", "price": 32000, "stock": 6}]
    )
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    reply = LLMResponse(
        model="gemini-3.5-flash-lite", text="Пионы — 32 000 ₸.", usage=Usage(4000, 200, 3000)
    )
    agent, _ = await make_agent(FakeLLM([understood("product"), reply]))
    await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="пионы есть?")

    customer, bot = await _messages(owner_engine, conversation_id)
    assert customer["role"] == "customer"
    assert customer["content"] == "пионы есть?"
    assert bot["role"] == "bot"
    assert bot["content"] == "Пионы — 32 000 ₸."
    assert bot["model"] == "gemini-3.5-flash-lite"
    assert (bot["tokens_in"], bot["tokens_out"], bot["cached_tokens"]) == (4100, 210, 3000)
    assert isinstance(bot["cost_usd"], Decimal) and bot["cost_usd"] > 0
    assert bot["latency_ms"] >= 0
    trace = bot["trace"]
    assert trace["intent"] == "product"
    assert [c["node"] for c in trace["llm_calls"]] == ["understand", "respond"]
    assert trace["llm_calls"][0]["model"] == "gemini-3.1-flash-lite"
    steps = {s["node"]: s for s in trace["steps"]}
    assert "PN-001" in steps["retrieve"]["found"]
    assert steps["guard_out"]["amounts"] == [32000]
    assert await _unanswered(owner_engine, tenant_id) == []


async def test_nothing_found_goes_to_unanswered(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    agent, _ = await make_agent(FakeLLM([understood("policy"), "Уточню у менеджера."]))
    await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="есть рассрочка?")
    assert await _unanswered(owner_engine, tenant_id) == [
        ("есть рассрочка?", "Уточню у менеджера.")
    ]


async def test_smalltalk_is_not_unanswered(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    agent, _ = await make_agent(FakeLLM([understood("smalltalk"), "Здравствуйте!"]))
    await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="привет")
    assert await _unanswered(owner_engine, tenant_id) == []


async def test_human_mode_saves_only_customer_message(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, mode="human")
    agent, _ = await make_agent(FakeLLM([]))
    await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="алло")
    assert [m["role"] for m in await _messages(owner_engine, conversation_id)] == ["customer"]
