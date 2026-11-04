import time
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from app.llm import LLM, LLMResponse, Message, Tool
from app.llm.pricing import UnknownModelError, cost_usd


def usage_entry(node: str, response: LLMResponse, latency_ms: int) -> dict[str, Any]:
    try:
        cost: str | None = str(cost_usd(response.model, response.usage))
    except UnknownModelError:
        cost = None
    return {
        "node": node,
        "model": response.model,
        "tokens_in": response.usage.input_tokens,
        "tokens_out": response.usage.output_tokens,
        "cached_tokens": response.usage.cached_tokens,
        "latency_ms": latency_ms,
        "cost_usd": cost,
    }


async def call_llm(
    llm: LLM,
    node: str,
    model: str,
    messages: Sequence[Message],
    *,
    tools: Sequence[Tool] | None = None,
    schema: type[BaseModel] | None = None,
) -> tuple[LLMResponse, dict[str, Any]]:
    started = time.perf_counter()
    response = await llm.generate(model, messages, tools=tools, response_schema=schema)
    return response, usage_entry(node, response, round((time.perf_counter() - started) * 1000))
