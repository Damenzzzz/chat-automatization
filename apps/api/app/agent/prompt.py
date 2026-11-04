import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BotProfile, Tenant

LANG_NAMES = {"ru": "русский", "kk": "казахский"}
REPLY_LANG = {
    "ru": "русском",
    "kk": "казахском",
    "mixed": "том же языке, что и покупатель (он пишет вперемешку — можно так же)",
}


@dataclass(frozen=True)
class ShopProfile:
    name: str
    niche: str | None = None
    city: str | None = None
    tone: str | None = None
    greeting: str | None = None
    rules: dict[str, Any] = field(default_factory=dict)
    languages: tuple[str, ...] = ("ru", "kk")
    version: int | None = None


async def load_profile(session: AsyncSession, tenant_id: uuid.UUID) -> ShopProfile:
    tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    profile = await session.scalar(
        select(BotProfile).where(BotProfile.tenant_id == tenant_id, BotProfile.is_active)
    )
    base = ShopProfile(
        name=tenant.name if tenant else "магазин",
        niche=tenant.niche if tenant else None,
        city=tenant.city if tenant else None,
    )
    if profile is None:
        return base
    return replace(
        base,
        tone=profile.tone,
        greeting=profile.greeting,
        rules=dict(profile.rules or {}),
        languages=tuple(profile.languages or ("ru", "kk")),
        version=profile.version,
    )


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₸"


def _rule_lines(rules: dict[str, Any]) -> list[str]:
    lines = []
    for key, value in rules.items():
        if key == "address_form":
            continue
        if isinstance(value, list):
            lines += [f"- {item}" for item in value]
        else:
            lines.append(f"- {value}")
    return lines


def system_prompt(profile: ShopProfile) -> str:
    about = ", ".join(x for x in (profile.niche, profile.city) if x)
    address = profile.rules.get("address_form", "вы")
    languages = ", ".join(LANG_NAMES.get(code, code) for code in profile.languages)
    parts = [
        f"Ты — консультант магазина «{profile.name}»" + (f" ({about})" if about else "") + ".",
        f"Тон: {profile.tone or 'вежливый и дружелюбный, коротко и по делу'}.",
        f"Обращайся к покупателю на «{address}».",
    ]
    if profile.greeting:
        parts.append(f"Приветствие в начале диалога: {profile.greeting}")
    parts += [
        f"Языки магазина: {languages}. Отвечай на языке покупателя — он указан в блоке"
        " «Данные для ответа».",
        "",
        "Правила:",
        "- Говори только о магазине: товары, наличие, цены, подбор, доставка, оплата, заказ."
        " На посторонние темы вежливо откажи и предложи помочь с покупкой.",
        "- Цены, остатки и артикулы бери только из блока «Данные для ответа» и из результатов"
        " инструментов. Никогда не придумывай цену; если её нет — скажи, что уточнишь"
        " у менеджера.",
        "- Суммы пиши в тенге со знаком ₸, например 24 000 ₸.",
        "- Если остаток 0 — скажи, что товара нет в наличии, и предложи похожий.",
        "- Нужен другой товар или подробности — вызови search_products, get_product или search_kb.",
        "- Для заказа собери товар, имя, телефон, адрес и время доставки и вызови create_lead.",
        "- Просят живого человека или ты не можешь помочь — вызови handoff.",
        "- Отвечай коротко, 1–4 предложения, без таблиц и markdown.",
    ]
    shop_rules = _rule_lines(profile.rules)
    if shop_rules:
        parts += ["", "Правила магазина:", *shop_rules]
    return "\n".join(parts)


def _product_line(item: dict[str, Any]) -> str:
    price = money(item["price"]) if item.get("price") is not None else "цена не указана"
    stock = item.get("stock")
    if stock is None:
        availability = "наличие уточнить"
    elif stock > 0:
        availability = f"в наличии {stock} шт."
    else:
        availability = "нет в наличии"
    sku = f"{item['sku']} " if item.get("sku") else ""
    return f"- {sku}«{item['name']}» — {price}, {availability}"


def context_block(
    *,
    lang: str,
    intent: str | None,
    slots: dict[str, Any] | None,
    context: list[dict[str, Any]],
    notes: list[str] | None = None,
) -> str:
    lines = ["[Данные для ответа]", f"Отвечай на {REPLY_LANG.get(lang, 'русском')} языке ({lang})."]
    if intent:
        lines.append(f"Намерение покупателя: {intent}.")
    known = {k: v for k, v in (slots or {}).items() if v is not None}
    if known:
        lines.append("Известно: " + "; ".join(f"{k} = {v}" for k, v in known.items()) + ".")
    products = [c for c in context if c.get("type") == "product"]
    chunks = [c for c in context if c.get("type") == "kb"]
    leads = [c for c in context if c.get("type") == "lead"]
    if products:
        lines += ["Товары из каталога (цены и остатки актуальные):", *map(_product_line, products)]
    if chunks:
        lines.append("База знаний магазина:")
        lines += [f"- {c.get('title') or c.get('source')}: {c['text']}" for c in chunks]
    for lead in leads:
        lines.append(f"Заявка №{lead['number']} создана, сумма {money(lead['total_kzt'])}.")
    lines += notes or []
    lines.append("[/Данные для ответа]")
    return "\n".join(lines)
