from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.llm import LLMError, Message, Usage
from app.llm.fake import FakeLLM
from app.llm.pricing import UnknownModelError, cost_usd


@pytest.mark.parametrize(
    ("model", "usage", "expected"),
    [
        ("gemini-3.1-flash-lite", Usage(900, 60), Decimal("0.000315")),
        ("gemini-3.5-flash-lite", Usage(4000, 200), Decimal("0.001700")),
        ("gemini-3.6-flash", Usage(4000, 200), Decimal("0.003750")),
        ("gemini-3.6-flash", Usage(1_000_000, 1_000_000), Decimal("4.500000")),
        ("gemini-3.5-flash-lite", Usage(4000, 200, cached_tokens=3000), Decimal("0.000890")),
        ("gemini-3.5-flash-lite", Usage(0, 0), Decimal("0.000000")),
    ],
)
def test_cost_usd(model: str, usage: Usage, expected: Decimal) -> None:
    assert cost_usd(model, usage) == expected


def test_cost_usd_unknown_model() -> None:
    with pytest.raises(UnknownModelError):
        cost_usd("gpt-4o", Usage(1, 1))


class Answer(BaseModel):
    value: int


async def test_fake_llm_follows_script() -> None:
    llm = FakeLLM(["привет", Answer(value=42), lambda call: f"echo:{call.messages[-1].text}"])
    msgs = [Message("user", "hi")]

    assert (await llm.generate("m", msgs)).text == "привет"
    assert (await llm.generate("m", msgs, response_schema=Answer)).parsed == Answer(value=42)
    assert (await llm.generate("m", msgs)).text == "echo:hi"
    with pytest.raises(LLMError):
        await llm.generate("m", msgs)
    assert [c.model for c in llm.calls] == ["m"] * 4
