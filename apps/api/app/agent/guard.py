import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.agent.prompt import ShopProfile, money
from app.catalog.normalize import sku_norm

NUMBER = r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
AMOUNT = re.compile(
    rf"(?<![\w.,])(?P<num>{NUMBER})"
    r"(?:\s*(?P<thousand>тыс\.?|тысяч\w*|мың)|(?P<k>[кkК])(?![а-яёa-z]))?"
    r"(?:\s*(?P<cur>₸|тг\.?|тенге|теңге|kzt))?",
    re.IGNORECASE,
)
NOISE = re.compile(
    r"\+?[78][\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"
    r"|\d{1,2}:\d{2}"
    r"|\d+(?:[.,]\d+)?\s*%"
    r"|\d{1,2}\.\d{1,2}\.\d{2,4}"
)
SENTENCE = re.compile(r"[!?\n]+|\.\s+(?=[A-ZА-ЯЁӘҒҚҢӨҰҮҺІ])")
SKU_LIKE = re.compile(r"(?<![\w-])[A-Za-zА-ЯЁа-яё]{1,5}-?\d{2,}[A-Za-z0-9-]*(?![\w-])")
MAX_TERMS = 4
MAX_BASE = 40
MAX_COUNT = 1000


@dataclass
class Amount:
    value: int
    text: str


@dataclass
class CheckResult:
    amounts: list[int] = field(default_factory=list)
    skus: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _value(match: re.Match[str]) -> int:
    raw = re.sub(r"[   ]", "", match["num"]).replace(",", ".")
    value = float(raw)
    if match["thousand"] or match["k"]:
        value *= 1000
    return round(value)


def numbers(text: str) -> set[int]:
    return {_value(m) for m in AMOUNT.finditer(NOISE.sub(" ", text))}


def amounts(text: str) -> list[Amount]:
    found: list[Amount] = []
    for sentence in SENTENCE.split(NOISE.sub(" ", text)):
        matches = list(AMOUNT.finditer(sentence))
        marked = [m for m in matches if m["cur"] or m["thousand"] or m["k"]]
        if not marked:
            continue
        for m in matches:
            value = _value(m)
            if m in marked or value >= 1000:
                found.append(Amount(value, m.group(0).strip()))
    return found


def _sums(base: Iterable[int]) -> set[int]:
    values = sorted({v for v in base if v > 0})[:MAX_BASE]
    allowed = set(values)
    layer = set(values)
    for _ in range(MAX_TERMS - 1):
        layer = {a + b for a in layer for b in values}
        allowed |= layer
    return allowed


def allowed_base(
    context: list[dict[str, Any]], profile: ShopProfile, customer_text: str, slots: dict[str, Any]
) -> set[int]:
    base: set[int] = set()
    for item in context:
        if item.get("type") == "product" and item.get("price") is not None:
            base.add(int(item["price"]))
        elif item.get("type") == "lead" and item.get("total_kzt") is not None:
            base.add(int(item["total_kzt"]))
        elif item.get("type") == "kb":
            base |= numbers(str(item.get("text", "")))
    profile_text = " ".join(
        [profile.tone or "", profile.greeting or "", *map(str, profile.rules.values())]
    )
    base |= numbers(profile_text)
    base |= numbers(customer_text)
    if slots.get("budget_max"):
        base.add(int(slots["budget_max"]))
    return base


def check_reply(
    reply: str,
    context: list[dict[str, Any]],
    profile: ShopProfile,
    customer_text: str = "",
    slots: dict[str, Any] | None = None,
) -> CheckResult:
    result = CheckResult()
    if not reply.strip():
        result.errors.append("ответ пустой")
        return result
    allowed = _sums(allowed_base(context, profile, customer_text, slots or {}))
    prices = {int(i["price"]) for i in context if i.get("type") == "product" and i.get("price")}
    counts = {n for n in numbers(reply) | numbers(customer_text) if 1 < n < MAX_COUNT}
    allowed |= {price * count for price in prices for count in counts}
    for amount in amounts(reply):
        result.amounts.append(amount.value)
        if amount.value not in allowed:
            result.errors.append(
                f"сумма «{amount.text}» ({money(amount.value)}) не совпадает с ценами товаров"
                " и правилами магазина"
            )
    known = {item.get("sku_norm") for item in context if item.get("type") == "product"}
    for token in SKU_LIKE.findall(reply):
        code = sku_norm(token)
        result.skus.append(code or token)
        if code not in known:
            result.errors.append(f"артикула «{token}» нет среди найденных товаров")
    return result
