import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.guard import check_reply
from app.agent.prompt import ShopProfile, context_block
from app.agent.tools import ToolBox
from app.agent.understand import Slots, Understanding
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation
from tests.conftest import RecordingQueue
from tests.fake_ml import FakeML, make_shop

CATALOG = [
    {"sku": "RS-101", "name": "Букет красных роз", "category": "Розы", "price": 24000, "stock": 0},
    {"sku": "PN-001", "name": "Букет пионов", "category": "Пионы", "price": 32000, "stock": 6},
    {"sku": "GF-601", "name": "Открытка", "category": "Открытки", "price": 1500, "stock": 40},
]


@pytest.fixture
async def shop(owner_engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await make_shop(owner_engine, CATALOG)
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    return tenant_id, conversation_id


def box(shop: tuple[uuid.UUID, uuid.UUID]) -> ToolBox:
    return ToolBox(shop[0], shop[1], FakeML(), RecordingQueue(), sandbox=True)


async def test_category_matches_by_part(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    found = await box(shop).search_products("букет", category="пион")
    assert [p["sku"] for p in found.result["products"]] == ["PN-001"]
    assert "note" not in found.result


async def test_unknown_category_is_dropped_with_note(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    found = await box(shop).search_products("букет", category="Тюльпаны")
    assert found.result["products"]
    assert "В категории «Тюльпаны» ничего нет" in found.result["note"]


async def test_budget_is_relaxed_and_said_out_loud(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    found = await box(shop).search_products("букет пионов", budget_max=1000)
    assert found.result["products"]
    assert "До 1 000 ₸ ничего не нашлось" in found.notes[0]
    assert check_reply("Пионы стоят 32 000 ₸.", found.context, ShopProfile(name="Цветы")).ok


async def test_out_of_stock_gets_alternatives(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    found = await box(shop).search_products("красные розы", category="Розы")
    skus = [p["sku"] for p in found.result["products"]]
    assert skus[0] == "RS-101"
    assert set(skus[1:]) == {"PN-001", "GF-601"}
    assert [c.get("alternative", False) for c in found.context] == [False, True, True]
    assert "похожие товары в наличии" in found.result["note"]
    block = context_block(lang="ru", intent="product", slots=None, context=found.context)
    assert "«Букет пионов» (похожий товар в наличии) — 32 000 ₸" in block


async def test_retrieve_passes_relax_note_to_model(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    understood = Understanding(
        lang="ru",
        intent="product",
        complexity="low",
        search_query="букет пионов",
        slots=Slots(budget_max=1000),
    )
    llm = FakeLLM([understood, "До 1 000 ₸ букетов нет, пионы стоят 32 000 ₸."])
    agent, _ = await make_agent(llm)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="Пионы до 1000?")
    assert "ближайшие варианты дороже" in llm.calls[1].messages[-1].text
    assert result.reply == "До 1 000 ₸ букетов нет, пионы стоят 32 000 ₸."
