import re
from typing import Any, Literal

from pydantic import BaseModel

BASE_FIELDS = ("name", "sku", "price", "stock", "category", "description", "image_url")
ATTRIBUTE_PREFIX = "attributes."

SYNONYMS: dict[str | None, tuple[str, ...]] = {
    "name": (
        "наименование",
        "название",
        "товар",
        "наименование товара",
        "номенклатура",
        "name",
        "product",
        "title",
        "атауы",
        "тауар",
    ),
    "sku": (
        "артикул",
        "код",
        "код товара",
        "sku",
        "артикул производителя",
        "oem",
        "vendor code",
        "article",
        "part number",
        "штрихкод",
        "баркод",
    ),
    "price": (
        "цена",
        "цена тг",
        "цена тенге",
        "цена ₸",
        "стоимость",
        "розничная цена",
        "цена розница",
        "розница",
        "price",
        "баға",
        "бағасы",
    ),
    "stock": (
        "остаток",
        "остатки",
        "количество",
        "кол во",
        "наличие",
        "в наличии",
        "склад",
        "stock",
        "qty",
        "quantity",
        "қалдық",
    ),
    "category": ("категория", "группа", "раздел", "вид", "category", "санат"),
    "description": ("описание", "описание товара", "description", "сипаттама"),
    "image_url": (
        "фото",
        "изображение",
        "картинка",
        "ссылка на фото",
        "фото товара",
        "image",
        "photo",
        "image url",
        "picture",
        "сурет",
    ),
    None: ("№", "#", "n", "п п", "no", "номер"),
}


def normalize_header(header: str) -> str:
    text = header.lower().replace("ё", "е")
    text = re.sub(r"[^\w₸№#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_LOOKUP = {normalize_header(s): field for field, values in SYNONYMS.items() for s in values}


def is_valid_field(field: str | None) -> bool:
    if field is None or field in BASE_FIELDS:
        return True
    return field.startswith(ATTRIBUTE_PREFIX) and len(field) > len(ATTRIBUTE_PREFIX)


class ColumnMapping(BaseModel):
    column: str
    field: str | None
    confidence: float
    samples: list[str] = []


class MappingProposal(BaseModel):
    columns: list[ColumnMapping]
    method: Literal["heuristic", "llm", "saved"]


def _guess(header: str) -> tuple[str | None, float]:
    norm = normalize_header(header)
    if not norm:
        return None, 0.0
    if norm in _LOOKUP:
        return _LOOKUP[norm], 0.95
    tokens = norm.split()
    for synonym, field in _LOOKUP.items():
        if field and len(synonym) > 2 and (tokens[0] == synonym or norm.startswith(synonym + " ")):
            return field, 0.7
    return ATTRIBUTE_PREFIX + norm, 0.4


def _samples(rows: list[list[Any]], index: int) -> list[str]:
    return [str(r[index]) for r in rows if index < len(r) and r[index] not in (None, "")][:5]


def heuristic_mapping(
    headers: list[str], rows: list[list[Any]], saved: dict[str, Any] | None = None
) -> MappingProposal:
    saved = saved or {}
    guesses = []
    for i, header in enumerate(headers):
        if header in saved and is_valid_field(saved[header]):
            guesses.append((header, saved[header], 1.0, i))
        else:
            field, confidence = _guess(header)
            guesses.append((header, field, confidence, i))

    best: dict[str, tuple[float, int]] = {}
    for _, field, confidence, i in guesses:
        if field in BASE_FIELDS and confidence > best.get(field, (-1.0, -1))[0]:
            best[field] = (confidence, i)

    columns = []
    for header, field, confidence, i in guesses:
        if field in BASE_FIELDS and best[field][1] != i:
            field, confidence = ATTRIBUTE_PREFIX + normalize_header(header), 0.3
        columns.append(
            ColumnMapping(
                column=header, field=field, confidence=confidence, samples=_samples(rows, i)
            )
        )
    method: Literal["heuristic", "saved"] = (
        "saved" if saved and all(h in saved for h in headers) else "heuristic"
    )
    return MappingProposal(columns=columns, method=method)
