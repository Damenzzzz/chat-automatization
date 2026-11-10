from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict, total=False):
    tenant_id: str
    conversation_id: str
    channel: str
    channel_id: str | None
    customer_external_id: str | None
    external_id: str | None
    media: list[dict[str, Any]]
    customer_message_id: str
    voice_failed: bool
    send_failed: bool
    paused: str | None
    human_mode: bool
    sandbox: bool
    messages: Annotated[list[AnyMessage], add_messages]
    lang: str
    intent: str
    complexity: str
    slots: dict[str, Any]
    search_query: str | None
    context: list[dict[str, Any]]
    tool_hops: int
    retries: int
    check_ok: bool
    check_errors: list[str]
    usage: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    reply: str | None
    flagged: bool
    started_at: float
    duplicate: str | None


def step(state: ChatState, node: str, **data: Any) -> list[dict[str, Any]]:
    return [*state.get("trace", []), {"node": node, **data}]
