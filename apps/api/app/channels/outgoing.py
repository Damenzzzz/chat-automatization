import re
from collections.abc import Iterable, Sequence
from typing import Any

from app.agent.prompt import money
from app.channels.types import Button, ProductCard

MAX_CARDS = 3
MAX_PAYLOAD_BYTES = 64
ORDER_TITLE = {"ru": "Заказать", "kk": "Тапсырыс беру"}
ORDER_TEXT = {"ru": "Хочу заказать {sku}", "kk": "{sku} тапсырыс бергім келеді"}
PAYLOAD = re.compile(r"^order:(ru|kk):(.+)$")


def order_button(sku: str | None, lang: str | None) -> Button | None:
    if not sku:
        return None
    code = "kk" if lang == "kk" else "ru"
    payload = f"order:{code}:{sku}"
    if len(payload.encode()) > MAX_PAYLOAD_BYTES:
        return None
    return Button(title=ORDER_TITLE[code], payload=payload)


def button_text(payload: str) -> str | None:
    match = PAYLOAD.match(payload)
    return ORDER_TEXT[match[1]].format(sku=match[2]) if match else None


def mentioned_products(reply: str, context: Iterable[dict[str, Any]]) -> list[str]:
    text = reply.casefold()
    ids = []
    for item in context:
        if item.get("type") != "product":
            continue
        names = (item.get("name"), item.get("sku"))
        if any(name and str(name).casefold() in text for name in names):
            ids.append(str(item["id"]))
    return ids[:MAX_CARDS]


def product_card(
    *, name: str, sku: str | None, price: int | None, images: Sequence[str], lang: str | None
) -> ProductCard:
    caption = name if price is None else f"{name}\n{money(price)}"
    button = order_button(sku, lang)
    image = next((url for url in images if url.startswith("https://")), None)
    return ProductCard(
        title=name, caption=caption, image_url=image, buttons=[button] if button else []
    )


def split_text(text: str, limit: int) -> list[str]:
    chunks = []
    rest = text.strip()
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = rest.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return [*chunks, rest] if rest else chunks


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
