import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MONEY = re.compile(
    r"^(?P<num>\d+(?:[.,]\d+)?)\s*(?P<mult>к|k|тыс\.?|тысяч\w*|мың)?\s*(?:₸|тг\.?|тенге|теңге|kzt)?$",
    re.IGNORECASE,
)
LEADING_INT = re.compile(r"^\s*(\d+)")
MAX_QTY = 999


def parse_money(value: Any) -> Any:
    """«12к», «12 000 ₸», 12000.0 → 12000; остальное отдаёт pydantic как есть."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value)
    if not isinstance(value, str):
        return value
    match = MONEY.match(re.sub(r"[\s  ]", "", value))
    if not match:
        return value
    amount = float(match["num"].replace(",", "."))
    return round(amount * 1000 if match["mult"] else amount)


def parse_count(value: Any) -> Any:
    if isinstance(value, str) and (match := LEADING_INT.match(value)):
        return int(match[1])
    if isinstance(value, float):
        return round(value)
    return value


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class SearchProductsArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=500)
    budget_max: int | None = Field(None, ge=0, le=1_000_000_000)
    in_stock: bool | None = None
    category: str | None = Field(None, max_length=200)

    @field_validator("budget_max", mode="before")
    @classmethod
    def _money(cls, value: Any) -> Any:
        return parse_money(value)


class GetProductArgs(ToolArgs):
    sku: str = Field(min_length=1, max_length=100)


class SearchKbArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=500)


class LeadItem(ToolArgs):
    sku: str = Field(min_length=1, max_length=100)
    qty: int = Field(1, ge=1)

    @field_validator("qty", mode="before")
    @classmethod
    def _qty(cls, value: Any) -> Any:
        return 1 if value is None else parse_count(value)

    @field_validator("qty")
    @classmethod
    def _cap(cls, value: int) -> int:
        return min(value, MAX_QTY)


class CreateLeadArgs(ToolArgs):
    items: list[LeadItem] = Field(max_length=50)
    contact_phone: str = Field(min_length=5, max_length=40)
    contact_name: str | None = Field(None, max_length=200)
    address: str | None = Field(None, max_length=500)
    delivery_time: str | None = Field(None, max_length=200)
    comment: str | None = Field(None, max_length=1000)


class HandoffArgs(ToolArgs):
    reason: str = Field("покупатель просит менеджера", max_length=500)


ARGS: dict[str, type[ToolArgs]] = {
    "search_products": SearchProductsArgs,
    "get_product": GetProductArgs,
    "search_kb": SearchKbArgs,
    "create_lead": CreateLeadArgs,
    "handoff": HandoffArgs,
}


def explain(error: ValidationError) -> str:
    parts = []
    for item in error.errors()[:3]:
        where = ".".join(str(p) for p in item["loc"]) or "аргументы"
        parts.append(f"{where}: {item['msg']}")
    return "; ".join(parts)
