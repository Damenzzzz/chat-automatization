from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.llm.types import LLMError, LLMResponse, Message, Tool, Usage

Step = LLMResponse | BaseModel | str | Exception | Callable[..., Any]


@dataclass
class FakeCall:
    model: str
    messages: list[Message]
    tools: list[Tool]
    response_schema: type[BaseModel] | None


@dataclass
class FakeLLM:
    """Отдаёт ответы по сценарию: строка → текст, BaseModel → parsed, Exception → raise."""

    script: list[Step] = field(default_factory=list)
    calls: list[FakeCall] = field(default_factory=list)
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=100, output_tokens=10))

    async def generate(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[Tool] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        call = FakeCall(model, list(messages), list(tools or []), response_schema)
        self.calls.append(call)
        if not self.script:
            raise LLMError("FakeLLM: сценарий закончился")
        step = self.script.pop(0)
        if callable(step) and not isinstance(step, BaseModel | LLMResponse):
            step = step(call)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, LLMResponse):
            return step
        if isinstance(step, BaseModel):
            return LLMResponse(
                model=model, text=step.model_dump_json(), parsed=step, usage=self.usage
            )
        return LLMResponse(model=model, text=str(step), usage=self.usage)
