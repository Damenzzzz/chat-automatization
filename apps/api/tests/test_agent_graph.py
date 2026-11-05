from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.understand import Understanding
from app.llm.fake import FakeLLM
from tests.agent_helpers import make_agent, make_conversation, nodes


async def test_smalltalk_path(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    agent, _ = await make_agent(
        FakeLLM([Understanding(lang="ru", intent="smalltalk", complexity="low"), "Здравствуйте!"])
    )
    result = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="привет")
    assert result.reply
    assert nodes(result.trace) == [
        "ingest",
        "guard_in",
        "understand",
        "respond",
        "guard_out",
        "send",
        "meter",
    ]


async def test_checkpointer_keeps_history_per_conversation(owner_engine: AsyncEngine) -> None:
    tenant_id, first = await make_conversation(owner_engine)
    _, second = await make_conversation(owner_engine, tenant_id)
    agent, _ = await make_agent()
    for text in ("привет", "есть пионы?"):
        await agent.run(tenant_id=tenant_id, conversation_id=first, text=text)
    await agent.run(tenant_id=tenant_id, conversation_id=second, text="салем")

    state = await agent.graph.aget_state({"configurable": {"thread_id": str(first)}})
    assert [m.type for m in state.values["messages"]] == ["human", "ai", "human", "ai"]
    other = await agent.graph.aget_state({"configurable": {"thread_id": str(second)}})
    assert len(other.values["messages"]) == 2


async def test_human_mode_stops_at_guard_in(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine, mode="human")
    agent, _ = await make_agent()
    result = await agent.run(tenant_id=tenant_id, conversation_id=conversation_id, text="алло")
    assert result.human_mode
    assert result.reply is None
    assert nodes(result.trace) == ["ingest", "guard_in"]


async def test_voice_goes_through_transcribe(owner_engine: AsyncEngine) -> None:
    tenant_id, conversation_id = await make_conversation(owner_engine)
    agent, _ = await make_agent()
    result = await agent.run(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        text="",
        media=[{"kind": "audio", "file_id": "voice"}],
    )
    assert nodes(result.trace)[:3] == ["ingest", "transcribe", "guard_in"]
