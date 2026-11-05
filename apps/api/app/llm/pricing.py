from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.llm.types import Usage

MILLION = Decimal(1_000_000)
CACHED_INPUT_RATIO = Decimal("0.1")
COST_QUANT = Decimal("0.000001")


@dataclass(frozen=True)
class ModelPrice:
    input_per_m: Decimal
    output_per_m: Decimal


MODEL_PRICES: dict[str, ModelPrice] = {
    "gemini-3.1-flash-lite": ModelPrice(Decimal("0.25"), Decimal("1.50")),
    "gemini-3.5-flash-lite": ModelPrice(Decimal("0.30"), Decimal("2.50")),
    "gemini-3.6-flash": ModelPrice(Decimal("0.75"), Decimal("3.75")),
}


class UnknownModelError(KeyError):
    pass


def cost_usd(model: str, usage: Usage, prices: Mapping[str, ModelPrice] = MODEL_PRICES) -> Decimal:
    try:
        price = prices[model]
    except KeyError as exc:
        raise UnknownModelError(model) from exc
    cached = min(usage.cached_tokens, usage.input_tokens)
    input_cost = (
        Decimal(usage.input_tokens - cached) + Decimal(cached) * CACHED_INPUT_RATIO
    ) * price.input_per_m
    output_cost = Decimal(usage.output_tokens) * price.output_per_m
    return ((input_cost + output_cost) / MILLION).quantize(COST_QUANT)
