import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from app.agent.state import ChatState, step
from app.core.queue import Queue
from app.db.session import tenant_session
from app.llm import LLM
from app.models import Conversation
from app.search.types import SearchML

log = structlog.get_logger()


@dataclass
class AgentDeps:
    llm: LLM | None
    ml: SearchML
    queue: Queue
    extra: dict[str, Any] = field(default_factory=dict)


def last_human(state: ChatState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


class AgentNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    def tenant(self, state: ChatState) -> uuid.UUID:
        return uuid.UUID(state["tenant_id"])

    async def ingest(self, state: ChatState) -> dict[str, Any]:
        async with tenant_session(self.tenant(state)) as session:
            mode = await session.scalar(
                select(Conversation.mode).where(
                    Conversation.id == uuid.UUID(state["conversation_id"])
                )
            )
        reset: dict[str, Any] = {
            "human_mode": mode == "human",
            "context": [],
            "tool_hops": 0,
            "retries": 0,
            "check_ok": False,
            "check_errors": [],
            "usage": [],
            "reply": None,
            "flagged": False,
            "started_at": time.time(),
        }
        reset["trace"] = [{"node": "ingest", "mode": mode}]
        return reset

    async def transcribe(self, state: ChatState) -> dict[str, Any]:
        return {"trace": step(state, "transcribe", skipped="шаг 8")}

    async def guard_in(self, state: ChatState) -> dict[str, Any]:
        return {"trace": step(state, "guard_in", human_mode=bool(state.get("human_mode")))}

    async def understand(self, state: ChatState) -> dict[str, Any]:
        return {"intent": "smalltalk", "lang": "ru", "trace": step(state, "understand")}

    async def retrieve(self, state: ChatState) -> dict[str, Any]:
        return {"trace": step(state, "retrieve")}

    async def kb(self, state: ChatState) -> dict[str, Any]:
        return {"trace": step(state, "kb")}

    async def order(self, state: ChatState) -> dict[str, Any]:
        return {"trace": step(state, "order")}

    async def handoff(self, state: ChatState) -> dict[str, Any]:
        return {"trace": step(state, "handoff")}

    async def respond(self, state: ChatState) -> dict[str, Any]:
        return {"messages": [AIMessage("Здравствуйте!")], "trace": step(state, "respond")}

    async def tools(self, state: ChatState) -> dict[str, Any]:
        return {"tool_hops": state.get("tool_hops", 0) + 1, "trace": step(state, "tools")}

    async def guard_out(self, state: ChatState) -> dict[str, Any]:
        return {"check_ok": True, "trace": step(state, "guard_out")}

    async def fallback(self, state: ChatState) -> dict[str, Any]:
        return {"trace": step(state, "fallback")}

    async def send(self, state: ChatState) -> dict[str, Any]:
        last = state["messages"][-1]
        return {"reply": str(last.content), "trace": step(state, "send", stub="шаг 8")}

    async def meter(self, state: ChatState) -> dict[str, Any]:
        return {"trace": step(state, "meter")}
