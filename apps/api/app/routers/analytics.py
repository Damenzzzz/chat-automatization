from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.analytics.overview import Metrics, collect_metrics, compare, dialogs_by_day
from app.analytics.period import Period, PeriodError, resolve_period
from app.auth.deps import Principal, TenantDb, require_role

router = APIRouter(prefix="/analytics", tags=["analytics"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]


def period_param(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> Period:
    try:
        return resolve_period(date_from, date_to)
    except PeriodError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


PeriodDep = Annotated[Period, Depends(period_param)]


class MetricsOut(BaseModel):
    date_from: date
    date_to: date
    dialogs: int
    bot_resolved: int
    bot_resolved_share: float | None
    leads: int
    leads_total_kzt: int
    avg_response_ms: int | None


class OverviewOut(BaseModel):
    current: MetricsOut
    previous: MetricsOut
    change_percent: dict[str, float | None]


class DayOut(BaseModel):
    day: date
    dialogs: int


def metrics_out(period: Period, metrics: Metrics) -> MetricsOut:
    return MetricsOut(
        date_from=period.first,
        date_to=period.last,
        dialogs=metrics.dialogs,
        bot_resolved=metrics.bot_resolved,
        bot_resolved_share=metrics.bot_resolved_share,
        leads=metrics.leads,
        leads_total_kzt=metrics.leads_total_kzt,
        avg_response_ms=metrics.avg_response_ms,
    )


@router.get("/overview")
async def overview(principal: Member, db: TenantDb, period: PeriodDep) -> OverviewOut:
    before = period.previous()
    current = await collect_metrics(db, period)
    previous = await collect_metrics(db, before)
    return OverviewOut(
        current=metrics_out(period, current),
        previous=metrics_out(before, previous),
        change_percent=compare(current, previous),
    )


@router.get("/dialogs_by_day")
async def by_day(principal: Member, db: TenantDb, period: PeriodDep) -> list[DayOut]:
    return [DayOut(day=day, dialogs=count) for day, count in await dialogs_by_day(db, period)]
