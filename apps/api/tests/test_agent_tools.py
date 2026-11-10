import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.tools import NOTIFY, ToolBox
from app.agent.understand import Slots, Understanding
from app.llm import ToolCall
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation
from tests.conftest import RecordingQueue
from tests.fake_ml import FakeML, make_shop

CATALOG = [
    {"sku": "PN-001", "name": "Букет из 15 розовых пионов", "price": 32000, "stock": 6},
    {"sku": "RS-101", "name": "Букет из 25 красных роз", "price": 24000, "stock": 0},
    {"sku": "GF-601", "name": "Открытка ручной работы", "price": 1500, "stock": 40},
]
KB = [{"source": "delivery", "title": "Доставка", "text": "Доставка по Алматы 2 000 ₸"}]


@pytest.fixture
async def shop(owner_engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await make_shop(owner_engine, CATALOG, kb=KB)
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    return tenant_id, conversation_id


def box(
    shop: tuple[uuid.UUID, uuid.UUID], *, sandbox: bool = False
) -> tuple[ToolBox, RecordingQueue]:
    queue = RecordingQueue()
    return ToolBox(shop[0], shop[1], FakeML(), queue, sandbox=sandbox), queue


async def _count(engine: AsyncEngine, table: str, tenant_id: uuid.UUID) -> int:
    async with engine.connect() as conn:
        value: int = await conn.scalar(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),  # noqa: S608
            {"t": tenant_id},
        )
        return value


async def test_search_products_tool(
    shop: tuple[uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    tools, _ = box(shop)
    outcome = await tools.search_products("розовые пионы", budget_max=30000)
    assert all(p["price"] <= 30000 for p in outcome.result["products"])
    assert outcome.context and outcome.context[0]["type"] == "product"
    assert await _count(owner_engine, "search_log", shop[0]) == 1

    sandbox_tools, _ = box(shop, sandbox=True)
    await sandbox_tools.search_products("пионы")
    assert await _count(owner_engine, "search_log", shop[0]) == 1


async def test_get_product_and_kb(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    tools, _ = box(shop)
    found = await tools.get_product("pn 001")
    assert found.result["product"]["price"] == 32000
    assert found.context[0]["sku_norm"] == "PN001"
    assert "error" in (await tools.get_product("ZZ-999")).result
    kb = await tools.search_kb("сколько стоит доставка")
    assert kb.result["articles"][0]["source"] == "delivery"


async def test_create_lead_prices_from_db(
    shop: tuple[uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    tools, queue = box(shop)
    outcome = await tools.create_lead(
        items=[{"sku": "PN-001", "qty": 2}, {"sku": "gf601"}],
        contact_phone="8 700 123 45 67",
        contact_name="Айгерим",
        address="Абая 10",
        delivery_time="сегодня к 18:00",
    )
    assert outcome.result["total_kzt"] == 2 * 32000 + 1500
    assert [c["type"] for c in outcome.context][-1] == "lead"
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT contact_phone, delivery_note, total_kzt FROM leads WHERE tenant_id = :t"
                ),
                {"t": shop[0]},
            )
        ).one()
    assert row == ("+77001234567", "сегодня к 18:00", 65500)
    assert queue.jobs == [(NOTIFY, (str(shop[0]), "lead.created", queue.jobs[0][1][2]))]


async def test_create_lead_validation(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    tools, queue = box(shop)
    assert "error" in (await tools.create_lead([{"sku": "PN-001"}], "123")).result
    assert "error" in (await tools.create_lead([{"sku": "XX-1"}], "+77001234567")).result
    assert "error" in (await tools.create_lead([], "+77001234567")).result
    assert queue.jobs == []


async def test_sandbox_lead_does_not_notify(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    tools, queue = box(shop, sandbox=True)
    outcome = await tools.create_lead([{"sku": "PN-001"}], "+77001234567")
    assert outcome.result["total_kzt"] == 32000
    assert queue.jobs == []


async def test_handoff_tool(shop: tuple[uuid.UUID, uuid.UUID], owner_engine: AsyncEngine) -> None:
    tools, queue = box(shop)
    outcome = await tools.handoff("жалоба")
    assert outcome.human_mode
    async with owner_engine.connect() as conn:
        mode = await conn.scalar(
            text("SELECT mode FROM conversations WHERE id = :c"), {"c": shop[1]}
        )
    assert mode == "human"
    assert queue.jobs[0][1][1] == "handoff"


async def test_run_dispatch_errors(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    tools, _ = box(shop)
    assert "error" in (await tools.run(ToolCall("drop_tables", {}))).result
    assert "error" in (await tools.run(ToolCall("get_product", {"bad": 1}))).result
    bad_qty = {"items": [{"sku": "RS-101", "qty": "2 шт"}], "contact_phone": "+77011234567"}
    assert "error" in (await tools.run(ToolCall("create_lead", bad_qty))).result
    ok = await tools.run(ToolCall("get_product", {"sku": "RS-101"}))
    assert ok.result["product"]["stock"] == 0


async def test_retrieve_node_puts_products_in_context(
    shop: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, conversation_id = shop
    llm = FakeLLM(
        [
            Understanding(
                lang="ru",
                intent="product",
                complexity="low",
                slots=Slots(sku="RS-101"),
                search_query="пионы",
            ),
            "Ответ",
        ]
    )
    agent, _ = await make_agent(llm)
    result = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="пионы?")
    retrieve = next(t for t in result.trace if t["node"] == "retrieve")
    assert retrieve["found"][0] == "RS-101"
    assert "PN-001" in retrieve["found"]


async def test_handoff_intent_switches_mode(
    shop: tuple[uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    tenant_id, conversation_id = shop
    llm = FakeLLM([Understanding(lang="ru", intent="human", complexity="low"), "Зову менеджера"])
    agent, queue = await make_agent(llm)
    result = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="менеджер")
    assert result.human_mode
    assert queue.jobs[0][1][1] == "handoff"
    second = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="алло")
    assert second.reply is None
