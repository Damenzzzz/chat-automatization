import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.analytics.grouping import Question, group_questions
from app.analytics.overview import Metrics, collect_metrics, compare, dialogs_by_day
from app.analytics.period import Period, PeriodError, resolve_period
from app.auth.deps import Principal, TenantDb, require_role
from app.core.config import get_settings
from app.mlclient import MLClient, get_ml_client
from app.models import Conversation, SearchLog, Unanswered

router = APIRouter(prefix="/analytics", tags=["analytics"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
MAX_UNANSWERED = 300


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
    spent_kzt: int
    found_dialogs: int
    leads_done: int


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
        spent_kzt=metrics.spent_kzt,
        found_dialogs=metrics.found_dialogs,
        leads_done=metrics.leads_done,
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


class TopQueryOut(BaseModel):
    query: str
    count: int
    in_stock: bool | None
    found: bool


@router.get("/top_queries")
async def top_queries(
    principal: Member,
    db: TenantDb,
    period: PeriodDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[TopQueryOut]:
    normalized = func.lower(func.trim(SearchLog.query))
    rows = await db.execute(
        select(
            normalized.label("query"),
            func.count(SearchLog.id).label("count"),
            func.bool_or(SearchLog.has_in_stock).label("in_stock"),
            func.max(SearchLog.result_count).label("max_results"),
        )
        .where(
            SearchLog.kind == "product",
            SearchLog.created_at >= period.start,
            SearchLog.created_at < period.end,
        )
        .group_by(normalized)
        .order_by(func.count(SearchLog.id).desc(), normalized)
        .limit(limit)
    )
    return [
        TopQueryOut(
            query=row.query, count=row.count, in_stock=row.in_stock, found=row.max_results > 0
        )
        for row in rows
    ]


class UnansweredGroupOut(BaseModel):
    question: str
    count: int
    ids: list[uuid.UUID]
    examples: list[str]
    last_asked_at: datetime | None


class UnansweredOut(BaseModel):
    grouped_by: Literal["embeddings", "text"]
    total: int
    groups: list[UnansweredGroupOut]


@router.get("/unanswered")
async def unanswered(
    principal: Member,
    db: TenantDb,
    ml: Annotated[MLClient, Depends(get_ml_client)],
    period: PeriodDep,
) -> UnansweredOut:
    rows = await db.execute(
        select(Unanswered.id, Unanswered.question, Unanswered.created_at)
        .outerjoin(Conversation, Conversation.id == Unanswered.conversation_id)
        .where(
            Unanswered.resolved_at.is_(None),
            Unanswered.created_at >= period.start,
            Unanswered.created_at < period.end,
            Conversation.sandbox.isnot(True),
        )
        .order_by(Unanswered.created_at.desc())
        .limit(MAX_UNANSWERED)
    )
    questions = [Question(row.id, row.question, row.created_at) for row in rows]
    groups, method = await group_questions(questions, ml, get_settings().unanswered_group_threshold)
    return UnansweredOut(
        grouped_by=method,
        total=len(questions),
        groups=[
            UnansweredGroupOut(
                question=g.question,
                count=g.count,
                ids=g.ids,
                examples=g.examples,
                last_asked_at=g.last_asked_at,
            )
            for g in groups
        ],
    )
