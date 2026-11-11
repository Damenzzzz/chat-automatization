import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select, update

from app.auth.identity import normalize_phone
from app.catalog.normalize import sku_norm
from app.core.poke import poke
from app.core.queue import Queue
from app.db.session import tenant_session
from app.llm import Tool, ToolCall
from app.models import Conversation, Lead, Product
from app.search import ProductFilters, search_kb, search_products
from app.search.types import KbHit, ProductHit, SearchML

log = structlog.get_logger()

NOTIFY = "notify_manager"
MAX_QTY = 999

TOOLS = [
    Tool(
        "search_products",
        "Поиск товаров в каталоге магазина. Возвращает до 5 товаров с актуальной ценой и остатком.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "что ищет покупатель"},
                "budget_max": {"type": "integer", "description": "максимальная цена в тенге"},
                "in_stock": {"type": "boolean", "description": "только в наличии"},
                "category": {"type": "string"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        "get_product",
        "Товар по артикулу: цена, остаток, описание.",
        {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
        },
    ),
    Tool(
        "search_kb",
        "Поиск в базе знаний магазина: доставка, оплата, возврат, адрес, график.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    Tool(
        "create_lead",
        "Оформить заявку на заказ, когда покупатель выбрал товары и оставил телефон."
        " Менеджер получит уведомление.",
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sku": {"type": "string"},
                            "qty": {"type": "integer", "minimum": 1},
                        },
                        "required": ["sku"],
                    },
                },
                "contact_name": {"type": "string"},
                "contact_phone": {"type": "string"},
                "address": {"type": "string"},
                "delivery_time": {"type": "string"},
                "comment": {"type": "string"},
            },
            "required": ["items", "contact_phone"],
        },
    ),
    Tool(
        "handoff",
        "Передать диалог живому менеджеру: покупатель просит человека, жалоба,"
        " или ты не можешь помочь.",
        {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    ),
]


def product_item(hit: ProductHit | Product) -> dict[str, Any]:
    return {
        "type": "product",
        "id": str(hit.id),
        "sku": hit.sku,
        "sku_norm": sku_norm(hit.sku),
        "name": hit.name,
        "category": hit.category,
        "price": hit.price,
        "stock": hit.stock,
    }


def kb_item(hit: KbHit) -> dict[str, Any]:
    return {
        "type": "kb",
        "id": str(hit.id),
        "source": hit.source,
        "title": hit.title,
        "text": hit.text,
    }


def merge_context(
    context: list[dict[str, Any]], items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    seen = {(c.get("type"), c.get("id")) for c in context}
    merged = list(context)
    for item in items:
        key = (item.get("type"), item.get("id"))
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def _public(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in ("type", "id", "sku_norm")}


@dataclass
class ToolOutcome:
    result: dict[str, Any]
    context: list[dict[str, Any]] = field(default_factory=list)
    human_mode: bool = False


@dataclass
class ToolBox:
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    ml: SearchML
    queue: Queue
    sandbox: bool = False
    lang: str | None = None

    async def notify(self, event: str, payload: dict[str, Any]) -> None:
        if self.sandbox:
            return
        await self.queue.enqueue(NOTIFY, str(self.tenant_id), event, payload)

    async def search_products(
        self,
        query: str,
        budget_max: int | None = None,
        in_stock: bool | None = None,
        category: str | None = None,
    ) -> ToolOutcome:
        filters = ProductFilters(price_max=budget_max, in_stock=bool(in_stock), category=category)
        async with tenant_session(self.tenant_id) as session:
            found = await search_products(
                session,
                query,
                filters,
                ml=self.ml,
                lang=self.lang,
                conversation_id=self.conversation_id,
                record=not self.sandbox,
            )
        items = [product_item(hit) for hit in found.items]
        return ToolOutcome({"products": [_public(i) for i in items]}, items)

    async def get_product(self, sku: str) -> ToolOutcome:
        code = sku_norm(sku)
        async with tenant_session(self.tenant_id) as session:
            product = await session.scalar(
                select(Product).where(Product.sku_norm == code, Product.is_active)
            )
        if product is None:
            return ToolOutcome({"error": f"товар с артикулом {sku} не найден"})
        item = product_item(product)
        return ToolOutcome(
            {"product": {**_public(item), "description": product.description}}, [item]
        )

    async def search_kb(self, query: str) -> ToolOutcome:
        async with tenant_session(self.tenant_id) as session:
            found = await search_kb(
                session,
                query,
                ml=self.ml,
                lang=self.lang,
                conversation_id=self.conversation_id,
                record=not self.sandbox,
            )
        items = [kb_item(hit) for hit in found.items]
        return ToolOutcome({"articles": [_public(i) for i in items]}, items)

    async def create_lead(
        self,
        items: list[dict[str, Any]],
        contact_phone: str,
        contact_name: str | None = None,
        address: str | None = None,
        delivery_time: str | None = None,
        comment: str | None = None,
    ) -> ToolOutcome:
        try:
            phone = normalize_phone(contact_phone)
        except ValueError:
            return ToolOutcome({"error": "телефон не распознан, попроси номер в формате +7…"})
        wanted = {
            sku_norm(str(i.get("sku", ""))): min(MAX_QTY, max(1, int(i.get("qty") or 1)))
            for i in items
        }
        wanted.pop(None, None)
        if not wanted:
            return ToolOutcome({"error": "в заявке нет товаров"})
        async with tenant_session(self.tenant_id) as session:
            rows = await session.scalars(
                select(Product).where(Product.sku_norm.in_(list(wanted)), Product.is_active)
            )
            products = {p.sku_norm: p for p in rows}
            missing = [code for code in wanted if code not in products]
            if missing:
                return ToolOutcome(
                    {"error": f"нет товаров с артикулами: {', '.join(map(str, missing))}"}
                )
            short = [
                f"{p.sku}: в наличии {p.stock}"
                for code, p in products.items()
                if p.stock is not None and wanted[code] > p.stock
            ]
            if short:
                return ToolOutcome(
                    {
                        "error": "не хватает на складе ("
                        + "; ".join(short)
                        + "): предложи доступное количество или передай диалог менеджеру"
                    }
                )
            lines: list[dict[str, Any]] = [
                {"sku": p.sku, "name": p.name, "qty": wanted[code], "price": p.price}
                for code, p in products.items()
            ]
            total = sum((p.price or 0) * wanted[code] for code, p in products.items())
            lead = Lead(
                tenant_id=self.tenant_id,
                conversation_id=self.conversation_id,
                items=lines,
                total_kzt=total,
                contact_name=contact_name,
                contact_phone=phone,
                address=address,
                delivery_note=delivery_time,
                comment=comment,
            )
            session.add(lead)
            await session.flush()
            number = str(lead.id)[:8]
            lead_id = lead.id
        await poke(self.tenant_id)
        await self.notify("lead.created", {"lead_id": str(lead_id), "total_kzt": total})
        context = [product_item(p) for p in products.values()]
        context.append({"type": "lead", "id": str(lead_id), "number": number, "total_kzt": total})
        return ToolOutcome({"lead_number": number, "total_kzt": total, "items": lines}, context)

    async def handoff(self, reason: str) -> ToolOutcome:
        async with tenant_session(self.tenant_id) as session:
            await session.execute(
                update(Conversation)
                .where(Conversation.id == self.conversation_id)
                .values(mode="human")
            )
        await self.notify(
            "handoff", {"conversation_id": str(self.conversation_id), "reason": reason}
        )
        return ToolOutcome(
            {"ok": True, "message": "менеджер подключится к диалогу"}, human_mode=True
        )

    async def run(self, call: ToolCall) -> ToolOutcome:
        handler = getattr(self, call.name, None) if call.name in {t.name for t in TOOLS} else None
        if handler is None:
            return ToolOutcome({"error": f"неизвестный инструмент {call.name}"})
        try:
            outcome: ToolOutcome = await handler(**call.args)
        except (TypeError, ValueError, AttributeError) as exc:
            return ToolOutcome({"error": f"неверные аргументы: {exc}"})
        return outcome
