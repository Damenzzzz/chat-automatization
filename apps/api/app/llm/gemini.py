import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
import structlog
from google import genai
from google.genai import errors
from google.genai import types as gt
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.llm.pricing import UnknownModelError, cost_usd
from app.llm.types import LLMError, LLMResponse, Message, Tool, ToolCall, Usage

log = structlog.get_logger()

Sleep = Callable[[float], Awaitable[None]]


def _cost(model: str, usage: Usage) -> object:
    try:
        return cost_usd(model, usage)
    except UnknownModelError:
        return None


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, errors.APIError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, TimeoutError | httpx.TransportError)


def _contents(messages: Sequence[Message]) -> tuple[str | None, list[gt.Content]]:
    system = "\n\n".join(m.text for m in messages if m.role == "system") or None
    contents = [
        gt.Content(role=m.role, parts=[gt.Part(text=m.text)])
        for m in messages
        if m.role != "system"
    ]
    return system, contents


def _usage(meta: gt.GenerateContentResponseUsageMetadata | None) -> Usage:
    if meta is None:
        return Usage()
    return Usage(
        input_tokens=meta.prompt_token_count or 0,
        output_tokens=(meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0),
        cached_tokens=meta.cached_content_token_count or 0,
    )


def parse_response(
    model: str, response: gt.GenerateContentResponse, schema: type[BaseModel] | None
) -> LLMResponse:
    texts: list[str] = []
    calls: list[ToolCall] = []
    candidate = response.candidates[0] if response.candidates else None
    for part in (candidate.content.parts or []) if candidate and candidate.content else []:
        if part.function_call and part.function_call.name:
            fc = part.function_call
            calls.append(ToolCall(name=fc.name or "", args=dict(fc.args or {}), id=fc.id))
        elif part.text and not part.thought:
            texts.append(part.text)
    text = "".join(texts)

    parsed = None
    if schema is not None:
        try:
            parsed = schema.model_validate_json(text)
        except ValidationError as exc:
            raise LLMError(f"ответ не соответствует схеме {schema.__name__}") from exc
    return LLMResponse(
        model=model,
        text=text,
        tool_calls=calls,
        parsed=parsed,
        usage=_usage(response.usage_metadata),
    )


class GeminiLLM:
    def __init__(
        self, settings: Settings, client: Any = None, sleep: Sleep = asyncio.sleep
    ) -> None:
        self.timeout = settings.llm_timeout
        self.max_retries = settings.llm_max_retries
        self._sleep = sleep
        if client is None:
            api_key = (
                settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
            )
            client = genai.Client(
                vertexai=settings.gemini_use_vertexai,
                api_key=api_key,
                http_options=gt.HttpOptions(timeout=int(self.timeout * 1000)),
            )
        self.client = client

    def _config(
        self,
        system: str | None,
        tools: Sequence[Tool] | None,
        schema: type[BaseModel] | None,
    ) -> gt.GenerateContentConfig:
        config = gt.GenerateContentConfig(
            system_instruction=system,
            automatic_function_calling=gt.AutomaticFunctionCallingConfig(disable=True),
        )
        if tools:
            config.tools = [
                gt.Tool(
                    function_declarations=[
                        gt.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters_json_schema=t.parameters,
                        )
                        for t in tools
                    ]
                )
            ]
        if schema is not None:
            config.response_mime_type = "application/json"
            config.response_json_schema = schema.model_json_schema()
        return config

    async def generate(
        self,
        model: str,
        messages: Sequence[Message],
        tools: Sequence[Tool] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> LLMResponse:
        system, contents = _contents(messages)
        config = self._config(system, tools, response_schema)

        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                raw = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    ),
                    timeout=self.timeout,
                )
            except Exception as exc:
                if not _is_retryable(exc) or attempt == self.max_retries:
                    log.warning("llm.error", model=model, attempt=attempt, error=repr(exc))
                    raise LLMError(f"{model}: {exc!r}") from exc
                delay = min(8.0, 0.5 * 2**attempt) * (0.5 + random.random() / 2)  # noqa: S311
                log.info("llm.retry", model=model, attempt=attempt, delay=round(delay, 2))
                await self._sleep(delay)
                continue

            result = parse_response(model, raw, response_schema)
            log.info(
                "llm.call",
                model=model,
                attempt=attempt,
                latency_ms=int((time.perf_counter() - started) * 1000),
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cached_tokens=result.usage.cached_tokens,
                tool_calls=len(result.tool_calls),
                cost_usd=str(_cost(model, result.usage)),
            )
            return result
        raise AssertionError("unreachable")
