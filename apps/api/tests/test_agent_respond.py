import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.llm import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation, nodes
from tests.fake_ml import make_shop

CATALOG = [{"sku": "PN-001", "name": "Букет из 15 розовых пионов", "price": 32000, "stock": 6}]


def understood(intent: str = "product", lang: str = "ru", complexity: str = "low") -> Understanding:
    return Understanding(lang=lang, intent=intent, complexity=complexity)


def tool_call(name: str = "get_product", **args: object) -> LLMResponse:
    return LLMResponse(
        model="gemini-3.5-flash-lite",
        tool_calls=[ToolCall(name, args or {"sku": "PN-001"}, signature=b"sig")],
        usage=Usage(10, 2),
    )


@pytest.fixture
async def shop(owner_engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id = await make_shop(owner_engine, CATALOG)
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    return tenant_id, conversation_id


async def test_tool_result_goes_back_to_model(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    llm = FakeLLM([understood("smalltalk"), tool_call(), "Пионы стоят 32 000 ₸."])
    agent, _ = await make_agent(llm)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="сколько PN-001?")

    assert result.reply == "Пионы стоят 32 000 ₸."
    assert nodes(result.trace).count("tools") == 1
    second = llm.calls[2].messages
    assert second[-2].role == "model"
    assert second[-2].tool_calls[0].signature == b"sig"
    assert second[-1].role == "tool"
    assert '"price": 32000' in second[-1].text
    assert "PN-001 «Букет из 15 розовых пионов» — 32 000 ₸" in second[-3].text


async def test_tool_loop_stops_after_three_hops(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    llm = FakeLLM([understood("smalltalk"), tool_call(), tool_call(), tool_call(), "Готово."])
    agent, _ = await make_agent(llm)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="?")

    assert nodes(result.trace).count("tools") == 3
    assert [len(c.tools) > 0 for c in llm.calls[1:]] == [True, True, True, False]
    assert "Инструменты больше недоступны" in llm.calls[-1].messages[-7].text
    assert result.reply == "Готово."


async def test_model_still_calling_tools_after_limit_goes_to_check(
    shop: tuple[uuid.UUID, uuid.UUID],
) -> None:
    llm = FakeLLM([understood("smalltalk"), *[tool_call() for _ in range(4)], "Ответ"])
    agent, _ = await make_agent(llm)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="?")
    path = nodes(result.trace)
    assert path.count("tools") == 3
    assert path[path.index("respond", path.index("tools") + 5) + 1] == "guard_out"


@pytest.mark.parametrize(
    ("complexity", "model"),
    [("low", "gemini-3.5-flash-lite"), ("high", "gemini-3.6-flash")],
)
async def test_model_cascade_by_complexity(
    shop: tuple[uuid.UUID, uuid.UUID], complexity: str, model: str
) -> None:
    llm = FakeLLM([understood("smalltalk", complexity=complexity), "Здравствуйте!"])
    agent, _ = await make_agent(llm)
    await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="привет")
    assert llm.calls[1].model == model


async def test_long_dialog_switches_to_complex_model(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    script: list[object] = []
    for _ in range(7):
        script += [understood("smalltalk"), "Ок"]
    llm = FakeLLM(script)  # type: ignore[arg-type]
    agent, _ = await make_agent(llm)
    for i in range(7):
        await agent.run(tenant_id=shop[0], conversation_id=shop[1], text=f"сообщение {i}")
    reply_models = [c.model for c in llm.calls if c.response_schema is None]
    assert reply_models[:6] == ["gemini-3.5-flash-lite"] * 6
    assert reply_models[6] == "gemini-3.6-flash"
    history = [m.role for m in llm.calls[-1].messages]
    assert history[0] == "system"
    assert history.count("model") == 6


@pytest.mark.parametrize(("lang", "phrase"), [("kk", "казахском"), ("ru", "русском")])
async def test_customer_language_is_in_prompt(
    shop: tuple[uuid.UUID, uuid.UUID], lang: str, phrase: str
) -> None:
    llm = FakeLLM([understood("smalltalk", lang=lang), "Сәлеметсіз бе!"])
    agent, _ = await make_agent(llm)
    await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="сәлем")
    messages = llm.calls[1].messages
    assert messages[0].role == "system"
    assert f"Отвечай на {phrase} языке ({lang})." in messages[-1].text


async def test_offtopic_gets_decline_note(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    llm = FakeLLM([understood("offtopic"), "Я помогаю только с покупками в магазине."])
    agent, _ = await make_agent(llm)
    await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="реши уравнение")
    assert "Вопрос не о магазине" in llm.calls[1].messages[-1].text


async def test_without_llm_replies_with_template(shop: tuple[uuid.UUID, uuid.UUID]) -> None:
    agent, _ = await make_agent(None)
    result = await agent.run(tenant_id=shop[0], conversation_id=shop[1], text="пионы")
    assert result.reply == "Уточню этот вопрос у менеджера и вернусь с ответом."
