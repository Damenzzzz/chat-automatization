import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.checkpoint import get_checkpointer
from app.agent.nodes import AgentDeps
from app.agent.runtime import Agent
from tests.conftest import RecordingQueue
from tests.fake_ml import FakeML


async def make_conversation(
    engine: AsyncEngine, tenant_id: uuid.UUID | None = None, mode: str = "bot"
) -> tuple[uuid.UUID, uuid.UUID]:
    async with engine.begin() as conn:
        if tenant_id is None:
            tenant_id = await conn.scalar(
                text("INSERT INTO tenants (name) VALUES ('Цветы') RETURNING id")
            )
        customer_id = await conn.scalar(
            text(
                "INSERT INTO customers (tenant_id, channel, external_id) "
                "VALUES (:t, 'web', :e) RETURNING id"
            ),
            {"t": tenant_id, "e": uuid.uuid4().hex},
        )
        conversation_id = await conn.scalar(
            text(
                "INSERT INTO conversations (tenant_id, customer_id, mode) "
                "VALUES (:t, :c, :m) RETURNING id"
            ),
            {"t": tenant_id, "c": customer_id, "m": mode},
        )
    assert tenant_id is not None
    return tenant_id, conversation_id


async def make_agent(
    llm: Any = None, ml: Any = None, channels: Any = None
) -> tuple[Agent, RecordingQueue]:
    queue = RecordingQueue()
    deps = AgentDeps(llm=llm, ml=ml or FakeML(), queue=queue, channels=channels)
    return Agent(deps, await get_checkpointer()), queue


def nodes(trace: list[dict[str, Any]]) -> list[str]:
    return [entry["node"] for entry in trace]
