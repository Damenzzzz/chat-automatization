import math
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.auth.deps import Principal, TenantDb, require_role
from app.billing.invoice import RequisitesNotConfiguredError, render_invoice, seller_from
from app.billing.ledger import get_balance
from app.core.config import get_settings
from app.models import LedgerEntry, Payment, Tenant

router = APIRouter(tags=["billing"])

Owner = Annotated[Principal, Depends(require_role("owner"))]
Member = Annotated[Principal, Depends(require_role("owner", "manager"))]

FORECAST_DAYS = 7
MIN_INVOICE_KZT = 1_000
MAX_INVOICE_KZT = 100_000_000
INVOICE_REUSE = timedelta(hours=24)


class BalanceOut(BaseModel):
    balance_kzt: int
    spent_7d_kzt: int
    replies_7d: int
    days_left: int | None
    last_topup_kzt: int | None


def days_left(balance: int, spent: int, days: int = FORECAST_DAYS) -> int | None:
    if spent <= 0:
        return None
    return max(balance, 0) * days // spent


def spending_days(first_charge: datetime | None, now: datetime) -> int:
    if first_charge is None:
        return FORECAST_DAYS
    return min(FORECAST_DAYS, max(1, math.ceil((now - first_charge) / timedelta(days=1))))


@router.get("/balance")
async def balance(principal: Member, db: TenantDb) -> BalanceOut:
    now = datetime.now(UTC)
    moment = now - timedelta(days=FORECAST_DAYS)
    spent, replies = (
        await db.execute(
            select(
                func.coalesce(-func.sum(LedgerEntry.amount_kzt), 0), func.count(LedgerEntry.id)
            ).where(LedgerEntry.type == "charge", LedgerEntry.created_at >= moment)
        )
    ).one()
    last_topup = await db.scalar(
        select(LedgerEntry.amount_kzt)
        .where(LedgerEntry.type == "topup")
        .order_by(LedgerEntry.created_at.desc())
        .limit(1)
    )
    first_charge = await db.scalar(
        select(func.min(LedgerEntry.created_at)).where(LedgerEntry.type == "charge")
    )
    current = await get_balance(db)
    return BalanceOut(
        balance_kzt=current,
        spent_7d_kzt=int(spent),
        replies_7d=int(replies),
        days_left=days_left(current, int(spent), spending_days(first_charge, now)),
        last_topup_kzt=last_topup,
    )


def local_date(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(get_settings().analytics_timezone)).date()


@router.get("/billing/invoice", response_class=Response)
async def invoice(
    principal: Owner,
    db: TenantDb,
    amount_kzt: Annotated[int, Query(ge=MIN_INVOICE_KZT, le=MAX_INVOICE_KZT)],
) -> Response:
    try:
        seller = seller_from(get_settings())
    except RequisitesNotConfiguredError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "billing_requisites_not_configured"
        ) from exc
    payment = await db.scalar(
        select(Payment)
        .where(
            Payment.provider == "invoice",
            Payment.status == "pending",
            Payment.amount_kzt == amount_kzt,
            Payment.created_at >= datetime.now(UTC) - INVOICE_REUSE,
        )
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    if payment is None:
        sequence = await db.scalar(text("SELECT nextval('invoice_no_seq')"))
        year = local_date(datetime.now(UTC)).year
        payment = Payment(
            tenant_id=principal.tenant_id,
            provider="invoice",
            amount_kzt=amount_kzt,
            invoice_no=f"SAT-{year}-{sequence:06d}",
        )
        db.add(payment)
        await db.flush()
    buyer = await db.scalar(select(Tenant.name).where(Tenant.id == principal.tenant_id))
    number = payment.invoice_no or ""
    content = render_invoice(
        number=number,
        issued=local_date(payment.created_at),
        amount_kzt=amount_kzt,
        buyer=buyer or "",
        seller=seller,
    )
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{number}.pdf"'},
    )
