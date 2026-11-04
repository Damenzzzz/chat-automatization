import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.guard import amounts, check_reply
from app.agent.prompt import ShopProfile
from app.agent.understand import Slots, Understanding
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation, nodes
from tests.fake_ml import make_shop

PROFILE = ShopProfile(name="Пион", rules={"delivery": "Доставка по Алматы 2 000 ₸"})
CONTEXT: list[dict[str, Any]] = [
    {"type": "product", "sku": "PN-001", "sku_norm": "PN001", "price": 22900, "stock": 3},
    {"type": "product", "sku": "GF-601", "sku_norm": "GF601", "price": 1500, "stock": 9},
    {"type": "kb", "source": "delivery", "text": "Срочная доставка за 2 часа — плюс 1 500 ₸"},
]


def ok(reply: str, customer_text: str = "", slots: dict[str, Any] | None = None) -> bool:
    return check_reply(reply, CONTEXT, PROFILE, customer_text, slots).ok


def test_price_plus_delivery_sum_passes() -> None:
    result = check_reply("22 900 + 2 000 = 24 900 ₸", CONTEXT, PROFILE)
    assert result.ok
    assert result.amounts == [22900, 2000, 24900]


@pytest.mark.parametrize(
    "reply",
    [
        "Букет PN-001 стоит 22 900 ₸, в наличии 3 шт.",
        "Цена 22900тг",
        "Около 22,9 тыс. ₸",
        "Два букета — 45 800 ₸, с открыткой 47 300 ₸.",
        "Срочная доставка плюс 1 500 ₸, итого 24 400 ₸",
        "Звоните +7 700 000 00 00 с 9:00 до 22:00, предоплата 50%. Букет 22 900 ₸",
        "Букет из 101 розы есть, 22 900 ₸.",
        "Сделаем к 8-го марта, без проблем!",
    ],
)
def test_allowed_amounts(reply: str) -> None:
    assert ok(reply), check_reply(reply, CONTEXT, PROFILE).errors


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ("Букет стоит 25 000 ₸", "25 000 ₸"),
        ("Отдадим за 20к", "20к"),
        ("Есть RS-101 за 22 900 ₸", "RS-101"),
        ("", "пустой"),
    ],
)
def test_rejected_replies(reply: str, error: str) -> None:
    result = check_reply(reply, CONTEXT, PROFILE)
    assert not result.ok
    assert error in " ".join(result.errors)


def test_customer_budget_can_be_repeated() -> None:
    assert ok("Под бюджет 12к подберу", customer_text="до 12к")
    assert ok("В пределах 15 000 ₸ есть варианты", slots={"budget_max": 15000})


def test_amounts_parsing() -> None:
    assert [a.value for a in amounts("от 3к до 5 тыс. ₸, 1 200 тг")] == [3000, 5000, 1200]


async def _mode(engine: AsyncEngine, conversation_id: uuid.UUID) -> str:
    async with engine.connect() as conn:
        mode: str = await conn.scalar(
            text("SELECT mode FROM conversations WHERE id = :c"), {"c": conversation_id}
        )
        return mode


@pytest.fixture
async def shop(owner_engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await make_shop(
        owner_engine, [{"sku": "PN-001", "name": "Розовые пионы", "price": 32000, "stock": 6}]
    )
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    return tenant_id, conversation_id


def product() -> Understanding:
    return Understanding(lang="ru", intent="product", complexity="low", slots=Slots(sku="PN-001"))


async def test_wrong_price_retries_then_falls_back(
    shop: tuple[uuid.UUID, uuid.UUID], owner_engine: AsyncEngine
) -> None:
    llm = FakeLLM([product(), "Пионы за 30 000 ₸", "Пионы за 31 000 ₸"])
    agent, queue = await make_agent(llm)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="сколько пионы?")

    path = nodes(result.trace)
    assert path.count("guard_out") == 2
    assert path[-3:] == ["fallback", "send", "meter"]
    assert "30 000 ₸" in llm.calls[2].messages[-1].text
    assert "не прошёл проверку" in llm.calls[2].messages[-1].text
    assert result.reply == "Уточню этот вопрос у менеджера и вернусь с ответом."
    assert result.human_mode
    assert await _mode(owner_engine, shop[1]) == "human"
    assert queue.jobs[0][1][1] == "handoff"

    state = await agent.graph.aget_state({"configurable": {"thread_id": str(shop[1])}})
    texts = [m.content for m in state.values["messages"]]
    assert "Пионы за 30 000 ₸" not in texts
    assert "Пионы за 31 000 ₸" not in texts


async def test_retry_with_correct_price_is_sent(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    llm = FakeLLM([product(), "Пионы за 30 000 ₸", "Пионы за 32 000 ₸"])
    agent, _ = await make_agent(llm)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="сколько пионы?")
    assert result.reply == "Пионы за 32 000 ₸"
    assert not result.human_mode
    assert "fallback" not in nodes(result.trace)
