from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.sql import Select

from app.automations.base import (
    Context,
    Outcome,
    Preview,
    PreviewItem,
    Recipients,
    Service,
    plural,
    web_url,
)
from app.models import Product

CHECK_EVERY = timedelta(minutes=55)
REMEMBER = 2000
LISTED = 15


class StockSettings(BaseModel):
    threshold: int = Field(default=3, ge=0, le=1000)
    include_out_of_stock: bool = True
    categories: list[str] = Field(default_factory=list, max_length=20)
    recipients: Recipients = "owner"

    @field_validator("categories")
    @classmethod
    def clean_categories(cls, value: list[str]) -> list[str]:
        return [name.strip()[:200] for name in value if name.strip()]


def low_stock_query(settings: StockSettings) -> Select[Any]:
    columns: tuple[Any, ...] = (Product.id, Product.name, Product.sku, Product.stock)
    query = select(*columns).where(
        Product.is_active, Product.stock.is_not(None), Product.stock <= settings.threshold
    )
    if not settings.include_out_of_stock:
        query = query.where(Product.stock > 0)
    if settings.categories:
        lowered = [name.lower() for name in settings.categories]
        query = query.where(func.lower(Product.category).in_(lowered))
    return query.order_by(Product.stock, Product.name).limit(REMEMBER)


def stock_line(row: Any) -> str:
    left = f"осталось {row.stock} шт." if row.stock else "нет в наличии"
    sku = f" ({row.sku})" if row.sku else ""
    return f"«{row.name}»{sku} — {left}"


def goods(count: int) -> str:
    return f"{count} {plural(count, 'товар', 'товара', 'товаров')}"


class Stock(Service[StockSettings]):
    kind = "stock"
    title = "Контроль остатков"
    description = (
        "Следит за остатками в каталоге и сообщает, когда товар заканчивается,"
        " пока бот ещё не начал отказывать покупателям."
    )
    settings_model = StockSettings

    def due(
        self,
        settings: StockSettings,
        state: dict[str, Any],
        last_run_at: datetime | None,
        ctx_now: datetime,
    ) -> bool:
        return last_run_at is None or ctx_now - last_run_at >= CHECK_EVERY

    async def preview(self, ctx: Context, settings: StockSettings) -> Preview:
        rows = (await ctx.session.execute(low_stock_query(settings))).all()
        return Preview(
            summary=f"Сейчас на исходе: {goods(len(rows))}"
            f" (остаток не больше {settings.threshold}).",
            items=[
                PreviewItem(
                    title=row.name,
                    detail=f"осталось {row.stock} шт." if row.stock else "нет в наличии",
                )
                for row in rows[:LISTED]
            ],
        )

    async def run(self, ctx: Context, settings: StockSettings) -> Outcome:
        rows = (await ctx.session.execute(low_stock_query(settings))).all()
        known = set(ctx.state.get("alerted", []))
        fresh = rows if ctx.manual else [row for row in rows if str(row.id) not in known]
        ctx.state["alerted"] = [str(row.id) for row in rows]
        details = {"new": len(fresh), "low": len(rows)}
        if not fresh:
            return Outcome("empty", "Новых товаров на исходе нет", details)
        lines = [f"Заканчиваются товары (остаток не больше {settings.threshold}):"]
        lines += [f"- {stock_line(row)}" for row in fresh[:LISTED]]
        if len(fresh) > LISTED:
            lines.append(f"и ещё {len(fresh) - LISTED}")
        lines.append(web_url("/products"))
        text = "\n".join(lines)
        sent = await ctx.tell(text, settings.recipients)
        ctx.note("low_stock", text, details)
        return Outcome("ok", f"На исходе: {goods(len(fresh))}", {**details, "sent": sent})
