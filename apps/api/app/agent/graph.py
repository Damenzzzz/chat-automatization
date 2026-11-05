from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.state import ChatState

MAX_TOOL_HOPS = 3
MAX_RETRIES = 1
INTENT_ROUTES = {
    "product": "retrieve",
    "policy": "kb",
    "order": "order",
    "human": "handoff",
    "smalltalk": "respond",
    "offtopic": "respond",
}
NODES = (
    "ingest",
    "transcribe",
    "guard_in",
    "understand",
    "retrieve",
    "kb",
    "order",
    "handoff",
    "respond",
    "tools",
    "guard_out",
    "fallback",
    "send",
    "meter",
)


class Node(Protocol):
    async def __call__(self, state: ChatState) -> dict[str, Any]: ...


def after_ingest(state: ChatState) -> str:
    return "transcribe" if state.get("media") else "guard_in"


def after_guard_in(state: ChatState) -> str:
    return END if state.get("human_mode") else "understand"


def after_understand(state: ChatState) -> str:
    return INTENT_ROUTES.get(state.get("intent", ""), "respond")


def after_respond(state: ChatState) -> str:
    last = state["messages"][-1]
    wants_tool = bool(getattr(last, "tool_calls", None))
    return "tools" if wants_tool and state.get("tool_hops", 0) < MAX_TOOL_HOPS else "guard_out"


def after_check(state: ChatState) -> str:
    if state.get("check_ok"):
        return "send"
    return "respond" if state.get("retries", 0) < MAX_RETRIES else "fallback"


def build_graph(
    nodes: Any, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    g: StateGraph[ChatState, Any, Any, Any] = StateGraph(ChatState)
    for name in NODES:
        g.add_node(name, getattr(nodes, name))

    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", after_ingest, ["transcribe", "guard_in"])
    g.add_edge("transcribe", "guard_in")
    g.add_conditional_edges("guard_in", after_guard_in, [END, "understand"])
    g.add_conditional_edges("understand", after_understand, sorted(set(INTENT_ROUTES.values())))
    for name in ("retrieve", "kb", "order", "handoff"):
        g.add_edge(name, "respond")
    g.add_conditional_edges("respond", after_respond, ["tools", "guard_out"])
    g.add_edge("tools", "respond")
    g.add_conditional_edges("guard_out", after_check, ["send", "respond", "fallback"])
    g.add_edge("fallback", "send")
    g.add_edge("send", "meter")
    g.add_edge("meter", END)
    return g.compile(checkpointer=checkpointer)
