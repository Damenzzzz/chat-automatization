import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.checkpoint import get_checkpointer
from app.agent.graph import build_graph
from app.agent.nodes import AgentDeps, AgentNodes
from app.agent.state import ChatState
from app.core.queue import Queue, get_queue
from app.llm import LLM, get_llm
from app.mlclient import MLClient, get_ml_client


@dataclass
class TurnResult:
    reply: str | None
    human_mode: bool
    intent: str | None
    lang: str | None
    trace: list[dict[str, Any]] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)


class Agent:
    def __init__(self, deps: AgentDeps, checkpointer: BaseCheckpointSaver[Any] | None) -> None:
        self.deps = deps
        self.graph = build_graph(AgentNodes(deps), checkpointer)

    async def run(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        text: str,
        channel: str = "web",
        sandbox: bool = False,
        channel_id: uuid.UUID | None = None,
        customer_external_id: str | None = None,
        external_id: str | None = None,
        media: list[dict[str, Any]] | None = None,
    ) -> TurnResult:
        incoming: ChatState = {
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation_id),
            "channel": channel,
            "sandbox": sandbox,
            "channel_id": str(channel_id) if channel_id else None,
            "customer_external_id": customer_external_id,
            "external_id": external_id,
            "media": media or [],
            "messages": [
                HumanMessage(
                    text,
                    id=f"in:{external_id}" if external_id else None,
                    additional_kwargs={"at": time.time()},
                )
            ],
        }
        state = await self.graph.ainvoke(
            incoming, config={"configurable": {"thread_id": str(conversation_id)}}
        )
        return TurnResult(
            reply=state.get("reply"),
            human_mode=bool(state.get("human_mode")),
            intent=state.get("intent"),
            lang=state.get("lang"),
            trace=state.get("trace", []),
            usage=state.get("usage", []),
        )

    async def remember_manager_reply(self, conversation_id: uuid.UUID, text: str) -> None:
        config: RunnableConfig = {"configurable": {"thread_id": str(conversation_id)}}
        if (await self.graph.aget_state(config)).values:
            await self.graph.aupdate_state(config, {"messages": [AIMessage(text)]}, as_node="meter")


async def get_agent(
    llm: Annotated[LLM | None, Depends(get_llm)],
    ml: Annotated[MLClient, Depends(get_ml_client)],
    queue: Annotated[Queue, Depends(get_queue)],
) -> Agent:
    return Agent(AgentDeps(llm=llm, ml=ml, queue=queue), await get_checkpointer())
