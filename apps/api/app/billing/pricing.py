import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.llm.pricing import COST_QUANT, MODEL_PRICES, ModelPrice, UnknownModelError, cost_usd
from app.llm.types import Usage

log = structlog.get_logger()

DEFAULT_MARKUP = Decimal(3)
MIN_REPLY_PRICE_KZT = 1


@dataclass(frozen=True)
class Pricing:
    markup: Decimal
    kzt_per_usd: Decimal
    model_prices: dict[str, ModelPrice] = field(default_factory=lambda: dict(MODEL_PRICES))


def reply_price_kzt(cost: Decimal, pricing: Pricing) -> int:
    return max(MIN_REPLY_PRICE_KZT, math.ceil(cost * pricing.markup * pricing.kzt_per_usd))


def turn_cost(usage: list[dict[str, Any]], pricing: Pricing) -> Decimal:
    total = Decimal(0)
    for entry in usage:
        tokens = Usage(entry["tokens_in"], entry["tokens_out"], entry["cached_tokens"])
        try:
            total += cost_usd(entry["model"], tokens, pricing.model_prices)
        except UnknownModelError:
            log.warning("billing.unknown_model", model=entry["model"])
    return total.quantize(COST_QUANT)


def parse_model_prices(raw: dict[str, Any]) -> dict[str, ModelPrice]:
    return {
        model: ModelPrice(Decimal(str(p["input_per_m"])), Decimal(str(p["output_per_m"])))
        for model, p in raw.items()
    }


async def load_pricing(session: AsyncSession) -> Pricing:
    row = (await session.execute(text("SELECT * FROM pricing_effective()"))).first()
    default_rate = get_settings().pricing_kzt_per_usd
    if row is None:
        return Pricing(DEFAULT_MARKUP, default_rate)
    return Pricing(
        markup=row.markup,
        kzt_per_usd=row.kzt_per_usd or default_rate,
        model_prices={**MODEL_PRICES, **parse_model_prices(row.model_prices)},
    )
