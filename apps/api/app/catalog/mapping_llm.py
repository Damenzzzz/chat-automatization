import json
from typing import Any

from pydantic import BaseModel, Field

from app.catalog.mapping import ColumnMapping, MappingProposal, enforce_unique, is_valid_field
from app.llm import LLM, Message

SYSTEM = """Ты сопоставляешь колонки прайс-листа магазина в Казахстане с полями каталога.
Поля:
- name — название товара (обязательно ровно одна колонка);
- sku — артикул, код, OEM-номер;
- price — розничная цена в тенге;
- stock — остаток или количество на складе;
- category — категория или группа;
- description — описание;
- image_url — ссылки на фото;
- attributes.<ключ> — прочие характеристики (цвет, размер, бренд), ключ короткий, строчными;
- null — служебная колонка, игнорировать.
Поля кроме attributes.* можно назначить только одной колонке.
Заголовки могут быть на русском, казахском или английском.
Для каждой колонки верни field и confidence от 0 до 1."""


class LlmColumn(BaseModel):
    column: str
    field: str | None
    confidence: float = Field(ge=0, le=1)


class LlmMapping(BaseModel):
    columns: list[LlmColumn]


def _prompt(headers: list[str], rows: list[list[Any]], draft: MappingProposal) -> str:
    sample = [
        dict(zip(headers, (str(v) if v is not None else "" for v in r), strict=False)) for r in rows
    ]
    return (
        f"Заголовки: {json.dumps(headers, ensure_ascii=False)}\n"
        f"Первые строки: {json.dumps(sample, ensure_ascii=False)}\n"
        "Черновик эвристики: "
        + json.dumps({c.column: c.field for c in draft.columns}, ensure_ascii=False)
    )


async def refine_with_llm(
    llm: LLM, model: str, headers: list[str], rows: list[list[Any]], draft: MappingProposal
) -> MappingProposal:
    response = await llm.generate(
        model,
        [Message("system", SYSTEM), Message("user", _prompt(headers, rows, draft))],
        response_schema=LlmMapping,
    )
    assert isinstance(response.parsed, LlmMapping)  # noqa: S101
    suggestions = {c.column: c for c in response.parsed.columns if is_valid_field(c.field)}

    merged: list[ColumnMapping] = []
    for col in draft.columns:
        hint = suggestions.get(col.column)
        if hint is not None and col.confidence < 1.0 and hint.confidence >= col.confidence:
            col = col.model_copy(update={"field": hint.field, "confidence": hint.confidence})
        merged.append(col)
    return MappingProposal(columns=enforce_unique(merged), method="llm")
