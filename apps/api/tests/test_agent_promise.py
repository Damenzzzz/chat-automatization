import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation
from tests.fake_ml import make_shop

KB = [{"source": "delivery", "title": "Доставка", "text": "Фото букета пришлём перед выездом"}]


async def test_promise_of_manager_hands_dialog_over(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, [], kb=KB)
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    understood = Understanding(lang="ru", intent="policy", complexity="low", search_query="букет")
    llm = FakeLLM([understood, "Уточню у менеджера, он скоро подключится."])
    agent, queue = await make_agent(llm)

    result = await agent.run(
        tenant_id=tenant_id, conversation_id=conversation_id, text="Можно вернуть букет?"
    )

    assert result.human_mode
    guard = next(t for t in result.trace if t["node"] == "guard_out")
    assert guard["promised_manager"] is True
    assert queue.jobs[0][1][1] == "handoff"
    async with owner_engine.connect() as conn:
        mode = await conn.scalar(
            text("SELECT mode FROM conversations WHERE id = :c"), {"c": conversation_id}
        )
        unanswered = await conn.scalar(
            text("SELECT count(*) FROM unanswered WHERE tenant_id = :t"), {"t": tenant_id}
        )
    assert (mode, unanswered) == ("human", 1)


async def test_plain_answer_keeps_bot(owner_engine: AsyncEngine) -> None:
    tenant_id = await make_shop(owner_engine, [], kb=KB)
    _, conversation_id = await make_conversation(owner_engine, tenant_id)
    understood = Understanding(lang="ru", intent="policy", complexity="low", search_query="фото")
    llm = FakeLLM([understood, "Фото букета пришлём перед выездом курьера."])
    agent, queue = await make_agent(llm)
    result = await agent.run(
        tenant_id=tenant_id, conversation_id=conversation_id, text="Пришлёте фото?"
    )
    assert not result.human_mode
    assert queue.jobs == []
    assert uuid.UUID(str(conversation_id))
