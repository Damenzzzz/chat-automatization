from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

Role = Literal["system", "user", "model"]


@dataclass(frozen=True)
class Message:
    role: Role
    text: str


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass(frozen=True)
class LLMResponse:
    model: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    parsed: BaseModel | None = None
    usage: Usage = field(default_factory=Usage)


class LLMError(Exception):
    pass


class LLM(Protocol):
    async def generate(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[Tool] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse: ...
