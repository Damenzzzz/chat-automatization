import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.nodes import AgentNodes
from app.agent.state import ChatState
from app.agent.tools import ToolBox
from app.agent.understand import Understanding
from app.channels.types import OutgoingMessage
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation
from tests.conftest import RecordingQueue
from tests.fake_ml import FakeML, make_shop

SMALLTALK = Understanding(lang="ru", intent="smalltalk", complexity="low")


class Sent:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send(self, channel_id: uuid.UUID, customer: str, message: OutgoingMessage) -> None:
        self.texts.append(message.text or "")

    async def download(self, channel_id: uuid.UUID, media: Any) -> bytes:
        return b""


async def _roles(engine: AsyncEngine, conversation_id: uuid.UUID) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT role FROM messages WHERE conversation_id = :c ORDER BY created_at"),
            {"c": conversation_id},
        )
        return [r.role for r in rows]


async def _charges(engine: AsyncEngine, tenant_id: uuid.UUID) -> int:
    async with engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM ledger WHERE tenant_id = :t AND type = 'charge'"),
            {"t": tenant_id},
        )
    return int(count or 0)


async def test_repeated_turn_is_answered_once(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    agent, _ = await make_agent(FakeLLM([SMALLTALK, "Здравствуйте!"]))
    turn: dict[str, Any] = {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "text": "привет",
    }

    await agent.run(**turn, external_id="m1")
    await agent.run(**turn, external_id="m1")

    assert await _roles(owner_engine, conversation_id) == ["customer", "bot"]
    assert await _charges(owner_engine, tenant_id) == 1


async def test_sent_reply_is_recorded_without_second_send(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter = AgentNodes.meter
    calls = 0

    async def flaky(self: AgentNodes, state: ChatState) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("база недоступна")
        return await meter(self, state)

    monkeypatch.setattr(AgentNodes, "meter", flaky)
    tenant_id, conversation_id = await make_conversation(owner_engine)
    sent = Sent()
    agent, _ = await make_agent(FakeLLM([SMALLTALK, "Здравствуйте!"]), channels=sent)
    turn: dict[str, Any] = {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "text": "привет",
        "channel_id": uuid.uuid4(),
        "customer_external_id": "c1",
        "external_id": "m1",
    }

    with pytest.raises(RuntimeError):
        await agent.run(**turn)
    await agent.run(**turn)

    assert sent.texts == ["Здравствуйте!"]
    assert await _roles(owner_engine, conversation_id) == ["customer", "bot"]
    assert await _charges(owner_engine, tenant_id) == 1


async def test_lead_is_not_created_above_stock(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(
        owner_engine, [{"sku": "PN-001", "name": "Розовые пионы", "price": 32000, "stock": 2}]
    )
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    box = ToolBox(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        ml=FakeML(),
        queue=RecordingQueue(),
        sandbox=False,
        lang="ru",
    )

    over = await box.create_lead([{"sku": "PN-001", "qty": 5}], "+77011234567")
    exact = await box.create_lead([{"sku": "PN-001", "qty": 2}], "+77011234567")

    assert "в наличии 2" in over.result["error"]
    assert exact.result["total_kzt"] == 64000
