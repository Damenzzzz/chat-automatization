import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agent.graph import build_graph
from app.agent.nodes import AgentDeps, AgentNodes
from app.agent.state import ChatState


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
        audio_url: str | None = None,
    ) -> TurnResult:
        incoming: ChatState = {
            "tenant_id": str(tenant_id),
            "conversation_id": str(conversation_id),
            "channel": channel,
            "sandbox": sandbox,
            "audio_url": audio_url,
            "messages": [HumanMessage(text)],
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
