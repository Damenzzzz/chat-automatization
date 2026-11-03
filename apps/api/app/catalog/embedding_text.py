from typing import Any


def product_text(
    name: str,
    category: str | None,
    description: str | None,
    attributes: dict[str, Any] | None,
    synonyms: str | None,
) -> str:
    parts = [name]
    if category:
        parts.append(f"Категория: {category}")
    if description:
        parts.append(description)
    if attributes:
        parts.append("; ".join(f"{k}: {v}" for k, v in attributes.items()))
    if synonyms:
        parts.append(f"Синонимы: {synonyms}")
    return "\n".join(parts)


def kb_text(title: str | None, text: str) -> str:
    return f"{title}\n{text}" if title else text
