import hashlib
import html
import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

SPACES = re.compile(r"[\s   ]+")
TAGS = re.compile(r"<[^>]+>")
CURRENCY = re.compile(r"(тг|тенге|kzt|₸|т\.)", re.IGNORECASE)
URL = re.compile(r"https?://[^\s,;]+")
NO_STOCK = {"нет", "нет в наличии", "отсутствует", "-", "—", "жоқ"}
UNKNOWN_STOCK = {"есть", "да", "в наличии", "+", "бар", "под заказ"}


class NormalizeError(ValueError):
    pass


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def clean_text(value: Any) -> str | None:
    if is_blank(value):
        return None
    text = html.unescape(TAGS.sub(" ", str(value)))
    text = SPACES.sub(" ", text).strip()
    return text or None


def clean_sku(value: Any) -> str | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return clean_text(value)


def sku_norm(sku: str | None) -> str | None:
    if sku is None:
        return None
    return re.sub(r"[ \t\n\r\f\v-]+", "", sku).upper() or None


def name_hash(name: str) -> str:
    key = SPACES.sub(" ", name.lower().replace("ё", "е")).strip()
    return hashlib.sha256(key.encode()).hexdigest()


def _to_decimal(raw: str) -> Decimal:
    text = SPACES.sub("", CURRENCY.sub("", raw)).replace("'", "")
    if "," in text and "." in text:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        text = text.replace(thousands, "").replace(decimal_sep, ".")
    elif "," in text or "." in text:
        sep = "," if "," in text else "."
        head, _, tail = text.rpartition(sep)
        if len(tail) == 3 and text.count(sep) >= 1 and head.replace(sep, "").isdigit():
            text = text.replace(sep, "")
        else:
            text = text.replace(",", ".")
    return Decimal(text)


def parse_price(value: Any) -> int | None:
    if is_blank(value):
        return None
    try:
        amount = Decimal(str(value)) if isinstance(value, int | float) else _to_decimal(str(value))
    except InvalidOperation as exc:
        raise NormalizeError(f"цена не распознана: «{value}»") from exc
    if amount < 0:
        raise NormalizeError(f"отрицательная цена: «{value}»")
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_stock(value: Any) -> int | None:
    if is_blank(value):
        return None
    if isinstance(value, int | float):
        number = int(value)
    else:
        text = SPACES.sub(" ", str(value)).strip().lower()
        if text in NO_STOCK:
            return 0
        if text in UNKNOWN_STOCK:
            return None
        match = re.fullmatch(r"(-?\d+)(?:[.,]0+)?\s*(шт\.?|штук|ед\.?|дана)?", text)
        if match is None:
            raise NormalizeError(f"остаток не распознан: «{value}»")
        number = int(match.group(1))
    if number < 0:
        raise NormalizeError(f"отрицательный остаток: «{value}»")
    return number


def parse_images(value: Any) -> list[str]:
    if is_blank(value):
        return []
    return URL.findall(str(value))


def content_hash(
    name: str, description: str | None, category: str | None, attributes: dict[str, Any]
) -> str:
    payload = json.dumps(
        {"name": name, "description": description, "category": category, "attributes": attributes},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
