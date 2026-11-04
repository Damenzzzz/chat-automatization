import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select

from app.agent.llmcall import call_llm
from app.agent.state import ChatState, step
from app.agent.understand import (
    MAX_INPUT_CHARS,
    Understanding,
    heuristic,
    is_injection,
    merge_slots,
    router_messages,
)
from app.core.config import get_settings
from app.core.queue import Queue
from app.db.session import tenant_session
from app.llm import LLM, LLMError
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
        text = last_human(state)
        flagged = is_injection(text) or len(text) > MAX_INPUT_CHARS
        return {
            "flagged": flagged,
            "trace": step(
                state, "guard_in", human_mode=bool(state.get("human_mode")), flagged=flagged
            ),
        }

    async def understand(self, state: ChatState) -> dict[str, Any]:
        text = last_human(state)[:MAX_INPUT_CHARS]
        usage = list(state.get("usage", []))
        source = "llm"
        if state.get("flagged"):
            result = heuristic(text).model_copy(update={"intent": "offtopic"})
            source = "guard"
        elif self.deps.llm is None:
            result, source = heuristic(text), "heuristic"
        else:
            try:
                response, entry = await call_llm(
                    self.deps.llm,
                    "understand",
                    get_settings().llm_model_router,
                    router_messages(state.get("messages", []), text),
                    schema=Understanding,
                )
                usage.append(entry)
                if not isinstance(response.parsed, Understanding):
                    raise LLMError("understand: нет structured output")
                result = response.parsed
            except LLMError as exc:
                log.warning("agent.understand_failed", error=str(exc))
                result, source = heuristic(text), "heuristic"
        slots = merge_slots(state.get("slots"), result.slots)
        return {
            "lang": result.lang,
            "intent": result.intent,
            "complexity": result.complexity,
            "slots": slots,
            "search_query": result.search_query or text,
            "usage": usage,
            "trace": step(
                state,
                "understand",
                source=source,
                lang=result.lang,
                intent=result.intent,
                complexity=result.complexity,
                slots=slots,
            ),
        }

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
