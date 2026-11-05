import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.core.config import get_settings
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation, nodes
from tests.billing_helpers import charges

SMALLTALK = Understanding(lang="ru", intent="smalltalk", complexity="low")


async def _bot_replies(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    count: int,
    age_minutes: int = 1,
) -> None:
    async with engine.begin() as conn:
        for _ in range(count):
            await conn.execute(
                text(
                    "INSERT INTO messages (tenant_id, conversation_id, role, content, created_at)"
                    " VALUES (:t, :c, 'bot', 'ответ', now() - make_interval(mins => :m))"
                ),
                {"t": tenant_id, "c": conversation_id, "m": age_minutes},
            )


async def _second_conversation_same_customer(
    engine: AsyncEngine, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> uuid.UUID:
    async with engine.begin() as conn:
        value: uuid.UUID = await conn.scalar(
            text(
                "INSERT INTO conversations (tenant_id, customer_id) SELECT tenant_id, customer_id"
                " FROM conversations WHERE id = :c RETURNING id"
            ),
            {"c": conversation_id},
        )
    return value


async def test_thirtieth_reply_is_allowed(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    await _bot_replies(owner_engine, tenant_id, conversation_id, 29)
    agent, _ = await make_agent(llm=FakeLLM([SMALLTALK, "Ответ номер 30"]))

    turn = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="ещё")

    assert turn.reply == "Ответ номер 30"
    assert turn.human_mode is False


async def test_thirty_first_reply_is_handed_off_without_llm(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    await _bot_replies(owner_engine, tenant_id, conversation_id, 30)
    llm = FakeLLM([])
    agent, queue = await make_agent(llm=llm)

    turn = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="ещё")

    assert llm.calls == []
    assert turn.human_mode is True
    assert "Менеджер" in (turn.reply or "")
    assert nodes(turn.trace) == ["ingest", "guard_in", "gate", "send", "meter"]
    assert next(s for s in turn.trace if s["node"] == "gate")["reason"] == "rate_limit"
    assert queue.jobs[-1][0] == "notify_manager"
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT mode, paused_reason FROM conversations WHERE id = :c"),
                {"c": conversation_id},
            )
        ).one()
    assert (row.mode, row.paused_reason) == ("human", "rate_limit")
    assert await charges(owner_engine, tenant_id) == []


async def test_replies_older_than_hour_do_not_count(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    await _bot_replies(owner_engine, tenant_id, conversation_id, 40, age_minutes=61)
    await _bot_replies(owner_engine, tenant_id, conversation_id, 29, age_minutes=59)
    agent, _ = await make_agent(llm=FakeLLM([SMALLTALK, "Можно"]))

    turn = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="ещё")

    assert turn.reply == "Можно"


async def test_limit_counts_all_dialogs_of_one_customer(owner_engine: AsyncEngine) -> None:
    tenant_id, first = await make_conversation(owner_engine)
    second = await _second_conversation_same_customer(owner_engine, tenant_id, first)
    await _bot_replies(owner_engine, tenant_id, first, 15)
    await _bot_replies(owner_engine, tenant_id, second, 15)
    agent, _ = await make_agent(llm=FakeLLM([]))

    turn = await agent.run(tenant_id=tenant_id, conversation_id=second, text="ещё")

    assert turn.human_mode is True


async def test_limit_is_per_customer_not_per_shop(owner_engine: AsyncEngine) -> None:
    tenant_id, busy = await make_conversation(owner_engine)
    _, calm = await make_conversation(owner_engine, tenant_id)
    await _bot_replies(owner_engine, tenant_id, busy, 30)
    agent, _ = await make_agent(llm=FakeLLM([SMALLTALK, "Здравствуйте"]))

    turn = await agent.run(tenant_id=tenant_id, conversation_id=calm, text="привет")

    assert turn.reply == "Здравствуйте"


async def test_customer_and_manager_messages_do_not_count(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    async with owner_engine.begin() as conn:
        for role in ("customer", "manager") * 20:
            await conn.execute(
                text(
                    "INSERT INTO messages (tenant_id, conversation_id, role, content)"
                    " VALUES (:t, :c, :r, 'x')"
                ),
                {"t": tenant_id, "c": conversation_id, "r": role},
            )
    agent, _ = await make_agent(llm=FakeLLM([SMALLTALK, "Да"]))
    turn = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="ещё")
    assert turn.reply == "Да"


async def test_sandbox_has_no_limit(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    await _bot_replies(owner_engine, tenant_id, conversation_id, 50)
    agent, _ = await make_agent(llm=FakeLLM([SMALLTALK, "Песочница"]))
    turn = await agent.run(
        tenant_id=tenant_id, conversation_id=conversation_id, text="ещё", sandbox=True
    )
    assert turn.reply == "Песочница"


async def test_limit_comes_from_settings(
    owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "bot_replies_per_hour", 2)
    tenant_id, conversation_id = await make_conversation(owner_engine)
    await _bot_replies(owner_engine, tenant_id, conversation_id, 2)
    agent, _ = await make_agent(llm=FakeLLM([]))
    turn: Any = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="ещё")
    assert turn.human_mode is True
