import base64
import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from app.agent.prompt import ShopProfile, context_block, system_prompt
from app.core.config import Settings
from app.llm import LLMResponse, Message, ToolCall

LONG_DIALOG = 12
HISTORY_LIMIT = 20

FALLBACK = {
    "ru": "Уточню этот вопрос у менеджера и вернусь с ответом.",
    "kk": "Бұл сұрақты менеджерден нақтылап, жауап беремін.",
    "mixed": "Уточню у менеджера и вернусь с ответом. Менеджерден нақтылап, жауап беремін.",
}


def dialog_length(messages: list[AnyMessage]) -> int:
    return sum(
        1
        for m in messages
        if isinstance(m, HumanMessage)
        or (isinstance(m, AIMessage) and m.content and not m.tool_calls)
    )


def pick_model(settings: Settings, complexity: str | None, messages: list[AnyMessage]) -> str:
    if complexity == "high" or dialog_length(messages) > LONG_DIALOG:
        return settings.llm_model_complex
    return settings.llm_model_reply


def turn_start(messages: list[AnyMessage]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return index
    return len(messages)


def _calls(message: AIMessage) -> tuple[ToolCall, ...]:
    meta = message.additional_kwargs.get("gemini_calls", [])
    calls = []
    for i, call in enumerate(message.tool_calls):
        extra = meta[i] if i < len(meta) else {}
        signature = extra.get("signature")
        calls.append(
            ToolCall(
                name=call["name"],
                args=dict(call["args"]),
                id=extra.get("id"),
                signature=base64.b64decode(signature) if signature else None,
            )
        )
    return tuple(calls)


def _convert(message: AnyMessage) -> Message | None:
    if isinstance(message, HumanMessage):
        return Message("user", str(message.content))
    if isinstance(message, AIMessage):
        return Message("model", str(message.content or ""), tool_calls=_calls(message))
    if isinstance(message, ToolMessage):
        return Message("tool", str(message.content), tool_name=message.name)
    return None


def build_messages(
    profile: ShopProfile,
    messages: list[AnyMessage],
    *,
    lang: str,
    intent: str | None,
    slots: dict[str, Any] | None,
    context: list[dict[str, Any]],
    notes: list[str],
) -> list[Message]:
    start = turn_start(messages)
    history = [
        m
        for m in messages[:start]
        if isinstance(m, HumanMessage)
        or (isinstance(m, AIMessage) and m.content and not m.tool_calls)
    ][-HISTORY_LIMIT:]
    out = [Message("system", system_prompt(profile))]
    out += [c for c in map(_convert, history) if c]
    for index, message in enumerate(messages[start:]):
        if index == 0 and isinstance(message, HumanMessage):
            block = context_block(
                lang=lang, intent=intent, slots=slots, context=context, notes=notes
            )
            out.append(Message("user", f"{block}\n\nСообщение покупателя:\n{message.content}"))
        elif converted := _convert(message):
            out.append(converted)
    return out


def ai_message(response: LLMResponse) -> AIMessage:
    tool_calls = []
    meta = []
    for call in response.tool_calls:
        tool_calls.append({"id": call.id or uuid.uuid4().hex, "name": call.name, "args": call.args})
        meta.append(
            {
                "id": call.id,
                "signature": base64.b64encode(call.signature).decode() if call.signature else None,
            }
        )
    return AIMessage(
        content=response.text,
        tool_calls=tool_calls,
        additional_kwargs={"gemini_calls": meta, "model": response.model},
    )


def tool_message(call_id: str, name: str, result: dict[str, Any]) -> ToolMessage:
    return ToolMessage(
        content=json.dumps(result, ensure_ascii=False, default=str), tool_call_id=call_id, name=name
    )
