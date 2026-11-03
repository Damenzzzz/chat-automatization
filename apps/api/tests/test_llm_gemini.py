import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors
from google.genai import types as gt
from pydantic import BaseModel

from app.core.config import get_settings
from app.llm import GeminiLLM, LLMError, Message, Tool, Usage


def _response(*parts: gt.Part, prompt: int = 100, out: int = 20, cached: int = 40) -> Any:
    return gt.GenerateContentResponse(
        candidates=[gt.Candidate(content=gt.Content(role="model", parts=list(parts)))],
        usage_metadata=gt.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt,
            candidates_token_count=out,
            cached_content_token_count=cached,
            thoughts_token_count=5,
        ),
    )


class FakeModels:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "hang":
            await asyncio.sleep(10)
        return outcome


def _llm(models: FakeModels, **overrides: Any) -> tuple[GeminiLLM, list[float]]:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    settings = get_settings().model_copy(update=overrides)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiLLM(settings, client=client, sleep=sleep), sleeps


USER = [Message("system", "Ты консультант."), Message("user", "Есть пионы?")]


async def test_text_and_usage() -> None:
    models = FakeModels(_response(gt.Part(text="Да, "), gt.Part(text="есть.")))
    llm, _ = _llm(models)

    result = await llm.generate("gemini-3.5-flash-lite", USER)

    assert result.text == "Да, есть."
    assert result.usage == Usage(input_tokens=100, output_tokens=25, cached_tokens=40)
    config = models.calls[0]["config"]
    assert config.system_instruction == "Ты консультант."
    assert [c.role for c in models.calls[0]["contents"]] == ["user"]


async def test_tool_calls() -> None:
    call = gt.Part(function_call=gt.FunctionCall(name="search_products", args={"query": "пионы"}))
    models = FakeModels(_response(call))
    llm, _ = _llm(models)
    tool = Tool("search_products", "Поиск товаров", {"type": "object", "properties": {}})

    result = await llm.generate("gemini-3.5-flash-lite", USER, tools=[tool])

    assert result.tool_calls[0].name == "search_products"
    assert result.tool_calls[0].args == {"query": "пионы"}
    declared = models.calls[0]["config"].tools[0].function_declarations[0]
    assert declared.name == "search_products"


class Intent(BaseModel):
    intent: str
    lang: str


async def test_structured_output() -> None:
    models = FakeModels(_response(gt.Part(text='{"intent": "product", "lang": "ru"}')))
    llm, _ = _llm(models)

    result = await llm.generate("gemini-3.1-flash-lite", USER, response_schema=Intent)

    assert result.parsed == Intent(intent="product", lang="ru")
    assert models.calls[0]["config"].response_mime_type == "application/json"


async def test_invalid_structured_output_raises() -> None:
    llm, _ = _llm(FakeModels(_response(gt.Part(text="не json"))))
    with pytest.raises(LLMError):
        await llm.generate("gemini-3.1-flash-lite", USER, response_schema=Intent)


async def test_retries_429_and_5xx_with_backoff() -> None:
    models = FakeModels(
        errors.ClientError(429, {"error": {"message": "quota"}}),
        errors.ServerError(503, {"error": {"message": "overloaded"}}),
        _response(gt.Part(text="ok")),
    )
    llm, sleeps = _llm(models)

    result = await llm.generate("gemini-3.5-flash-lite", USER)

    assert result.text == "ok"
    assert len(models.calls) == 3
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0] * 0.9


async def test_client_error_is_not_retried() -> None:
    models = FakeModels(errors.ClientError(400, {"error": {"message": "bad"}}))
    llm, sleeps = _llm(models)

    with pytest.raises(LLMError):
        await llm.generate("gemini-3.5-flash-lite", USER)
    assert len(models.calls) == 1 and sleeps == []


async def test_gives_up_after_max_retries() -> None:
    models = FakeModels(*[errors.ServerError(500, {"error": {"message": "x"}})] * 3)
    llm, _ = _llm(models, llm_max_retries=2)

    with pytest.raises(LLMError):
        await llm.generate("gemini-3.5-flash-lite", USER)
    assert len(models.calls) == 3


async def test_timeout_is_retried() -> None:
    models = FakeModels("hang", _response(gt.Part(text="ok")))
    llm, _ = _llm(models, llm_timeout=0.05)

    assert (await llm.generate("gemini-3.5-flash-lite", USER)).text == "ok"
