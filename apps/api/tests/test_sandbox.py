import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.sandbox import AutotestPlan, AutotestQuestion, Verdict
from app.agent.understand import Understanding
from app.llm import LLMResponse, Message, Tool, Usage, get_llm
from app.llm.fake import FakeLLM
from app.mlclient import get_ml_client
from tests.conftest import FakeSender, create_user, login
from tests.fake_ml import FakeML, make_shop


class ShopLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, type[BaseModel] | None]] = []

    async def generate(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[Tool] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        self.calls.append((model, response_schema))
        parsed: BaseModel | None = None
        body = messages[-1].text
        if response_schema is AutotestPlan:
            parsed = AutotestPlan(
                questions=[
                    AutotestQuestion(
                        question="Сколько стоят розовые пионы?",
                        kind="product",
                        lang="ru",
                        expected="PN-001, 32 000 ₸",
                    ),
                    AutotestQuestion(
                        question="Жеткізу бар ма?", kind="policy", lang="kk", expected="2 000 ₸"
                    ),
                ]
            )
        elif response_schema is Understanding:
            kind = "policy" if "Жеткізу" in body else "product"
            parsed = Understanding(lang="ru", intent=kind, complexity="low")
        elif response_schema is Verdict:
            good = "32 000 ₸" in body.split("Ответ бота:")[1]
            parsed = Verdict(correct=good, reason="цена из каталога" if good else "нет цены")
        if parsed is not None:
            return LLMResponse(model=model, text=parsed.model_dump_json(), parsed=parsed)
        reply = "Розовые пионы — 32 000 ₸." if "пионы" in body else "Доставка бар."
        return LLMResponse(model=model, text=reply, usage=Usage(100, 10))


@pytest.fixture
async def shop_owner(
    client: AsyncClient, sender: FakeSender, owner_engine: AsyncEngine, app: FastAPI
) -> uuid.UUID:
    app.dependency_overrides[get_ml_client] = FakeML
    tenant_id = await make_shop(
        owner_engine,
        [{"sku": "PN-001", "name": "Розовые пионы", "price": 32000, "stock": 6}],
        kb=[{"source": "delivery", "title": "Доставка", "text": "Доставка 2 000 ₸"}],
    )
    _, _, phone = await create_user(owner_engine, tenant_id=tenant_id)
    await login(client, sender, phone)
    return tenant_id


async def test_sandbox_chat_keeps_session(
    client: AsyncClient, shop_owner: uuid.UUID, owner_engine: AsyncEngine, app: FastAPI
) -> None:
    llm = FakeLLM(
        [
            Understanding(lang="ru", intent="product", complexity="low"),
            "Розовые пионы — 32 000 ₸.",
            Understanding(lang="ru", intent="smalltalk", complexity="low"),
            "Пожалуйста!",
        ]
    )
    app.dependency_overrides[get_llm] = lambda: llm
    first = await client.post("/sandbox/chat", json={"message": "пионы?", "session_id": "s1"})
    second = await client.post("/sandbox/chat", json={"message": "спасибо", "session_id": "s1"})
    other = await client.post("/sandbox/chat", json={"message": "x", "session_id": "s2"})

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["reply"] == "Розовые пионы — 32 000 ₸."
    assert body["intent"] == "product"
    assert [s["node"] for s in body["trace"]][-1] == "meter"
    assert second.json()["conversation_id"] == body["conversation_id"]
    assert other.json()["conversation_id"] != body["conversation_id"]
    assert len(llm.calls[3].messages) == 4

    async with owner_engine.connect() as conn:
        sandbox = await conn.scalar(
            text("SELECT sandbox FROM conversations WHERE id = :c"), {"c": body["conversation_id"]}
        )
        logged = await conn.scalar(
            text("SELECT count(*) FROM search_log WHERE tenant_id = :t"), {"t": shop_owner}
        )
    assert sandbox is True
    assert logged == 0


async def test_sandbox_chat_without_llm(client: AsyncClient, shop_owner: uuid.UUID) -> None:
    response = await client.post("/sandbox/chat", json={"message": "пионы", "session_id": "a"})
    assert response.status_code == 200
    assert response.json()["reply"] == "Уточню этот вопрос у менеджера и вернусь с ответом."


async def test_sandbox_requires_shop_member(client: AsyncClient) -> None:
    response = await client.post("/sandbox/chat", json={"message": "x", "session_id": "a"})
    assert response.status_code == 401


async def test_autotest_judges_answers(
    client: AsyncClient, shop_owner: uuid.UUID, app: FastAPI
) -> None:
    llm = ShopLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    response = await client.post("/sandbox/autotest", json={"count": 2})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["total"] == 2
    assert body["correct"] == 1
    verdicts = {item["question"]: item for item in body["items"]}
    assert verdicts["Сколько стоят розовые пионы?"]["correct"] is True
    assert verdicts["Жеткізу бар ма?"]["reason"] == "нет цены"
    judges = [model for model, schema in llm.calls if schema is Verdict]
    assert judges == ["gemini-3.5-flash-lite"] * 2


async def test_autotest_needs_llm(client: AsyncClient, shop_owner: uuid.UUID) -> None:
    assert (await client.post("/sandbox/autotest")).status_code == 503
