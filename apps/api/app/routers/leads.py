import csv
import io
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import String, case, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.auth.deps import Principal, TenantDb, require_role
from app.core.poke import poke
from app.models import Conversation, Customer, Lead, User

router = APIRouter(prefix="/leads", tags=["leads"])
log = structlog.get_logger()

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
Owner = Annotated[Principal, Depends(require_role("owner"))]
LeadStatus = Literal["new", "in_progress", "done", "cancelled"]
CancelReason = Literal["price", "no_stock", "no_answer", "changed_mind", "duplicate", "other"]
ChannelType = Literal["whatsapp", "instagram", "telegram", "web"]
OPEN = ("new", "in_progress")
USER_LABEL = func.coalesce(User.name, User.email, User.phone)
EXPORT_LIMIT = 5000
BULK_LIMIT = 100

STATUS_RU = {
    "new": "Новая",
    "in_progress": "В работе",
    "done": "Выполнена",
    "cancelled": "Отменена",
}
REASON_RU = {
    "price": "Дорого",
    "no_stock": "Нет в наличии",
    "no_answer": "Не отвечает",
    "changed_mind": "Передумал",
    "duplicate": "Дубль",
    "other": "Другое",
}


class LeadOut(BaseModel):
    id: uuid.UUID
    number: str
    conversation_id: uuid.UUID | None
    items: list[Any]
    total_kzt: int | None
    contact_name: str | None
    contact_phone: str | None
    address: str | None
    delivery_at: datetime | None
    delivery_note: str | None
    comment: str | None
    status: str
    assignee_id: uuid.UUID | None
    assignee_name: str | None
    cancel_reason: str | None
    remind_at: datetime | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class LeadRow(LeadOut):
    channel: str | None
    tags: list[str]


class LeadCounts(BaseModel):
    new: int
    in_progress: int
    done: int
    cancelled: int
    overdue: int
    mine: int


class LeadList(BaseModel):
    items: list[LeadRow]
    counts: LeadCounts
    next_before: datetime | None


class LeadIn(BaseModel):
    status: LeadStatus | None = None
    assignee_id: uuid.UUID | None = None
    cancel_reason: CancelReason | None = None
    remind_at: AwareDatetime | None = None
    note: str | None = Field(default=None, max_length=2000)


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=BULK_LIMIT)
    status: LeadStatus | None = None
    assignee_id: uuid.UUID | None = None


class BulkOut(BaseModel):
    updated: int


def lead_number(lead_id: uuid.UUID) -> str:
    return str(lead_id)[:8]


def lead_out(lead: Lead, assignee_name: str | None = None) -> LeadOut:
    return LeadOut(
        id=lead.id,
        number=lead_number(lead.id),
        conversation_id=lead.conversation_id,
        items=lead.items,
        total_kzt=lead.total_kzt,
        contact_name=lead.contact_name,
        contact_phone=lead.contact_phone,
        address=lead.address,
        delivery_at=lead.delivery_at,
        delivery_note=lead.delivery_note,
        comment=lead.comment,
        status=lead.status,
        assignee_id=lead.assignee_id,
        assignee_name=assignee_name,
        cancel_reason=lead.cancel_reason,
        remind_at=lead.remind_at,
        note=lead.note,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


async def member_names(db: AsyncSession, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {user_id for user_id in ids if user_id}
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, USER_LABEL).where(User.id.in_(wanted)))
    return {user_id: label for user_id, label in rows}


async def ensure_member(db: AsyncSession, user_id: uuid.UUID) -> None:
    found = await db.scalar(
        select(User.id).where(
            User.id == user_id, User.is_active, User.role.in_(("owner", "manager"))
        )
    )
    if found is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "assignee_not_found")


def like_pattern(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def filtered(
    principal: Principal,
    status_: str | None,
    assignee: str | None,
    channel: str | None,
    q: str | None,
    due: bool,
) -> Select[Any]:
    columns: tuple[Any, ...] = (Lead, Customer.channel, Customer.tags, USER_LABEL)
    query = (
        select(*columns)
        .outerjoin(Conversation, Conversation.id == Lead.conversation_id)
        .outerjoin(Customer, Customer.id == Conversation.customer_id)
        .outerjoin(User, User.id == Lead.assignee_id)
    )
    if status_:
        query = query.where(Lead.status == status_)
    if assignee == "me":
        query = query.where(Lead.assignee_id == principal.user_id)
    elif assignee == "none":
        query = query.where(Lead.assignee_id.is_(None))
    elif assignee:
        try:
            query = query.where(Lead.assignee_id == uuid.UUID(assignee))
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "assignee_invalid") from exc
    if channel:
        query = query.where(Customer.channel == channel)
    if due:
        query = query.where(Lead.status.in_(OPEN), Lead.remind_at <= func.now())
    if q and q.strip():
        text = q.strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        found = [
            Lead.contact_name.ilike(like_pattern(text)),
            cast(Lead.id, String).like(like_pattern(text.lower())[1:]),
        ]
        if len(digits) >= 3:
            found.append(Lead.contact_phone.like(f"%{digits}%"))
        query = query.where(or_(*found))
    return query


async def lead_counts(db: AsyncSession, principal: Principal) -> LeadCounts:
    is_open = Lead.status.in_(OPEN)
    row = (
        await db.execute(
            select(
                func.count(case((Lead.status == "new", 1))),
                func.count(case((Lead.status == "in_progress", 1))),
                func.count(case((Lead.status == "done", 1))),
                func.count(case((Lead.status == "cancelled", 1))),
                func.count(case((is_open & (Lead.remind_at <= func.now()), 1))),
                func.count(case((is_open & (Lead.assignee_id == principal.user_id), 1))),
            )
        )
    ).one()
    return LeadCounts(
        new=row[0], in_progress=row[1], done=row[2], cancelled=row[3], overdue=row[4], mine=row[5]
    )


def lead_row(row: Any) -> LeadRow:
    lead, channel, tags, assignee_name = row
    return LeadRow(**lead_out(lead, assignee_name).model_dump(), channel=channel, tags=tags or [])


@router.get("")
async def list_leads(
    principal: Member,
    db: TenantDb,
    status_: Annotated[LeadStatus | None, Query(alias="status")] = None,
    assignee: Annotated[str | None, Query(max_length=36)] = None,
    channel: ChannelType | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    due: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: datetime | None = None,
) -> LeadList:
    query = filtered(principal, status_, assignee, channel, q, due)
    if before:
        query = query.where(Lead.created_at < before)
    rows = (await db.execute(query.order_by(Lead.created_at.desc()).limit(limit + 1))).all()
    items = [lead_row(row) for row in rows[:limit]]
    return LeadList(
        items=items,
        counts=await lead_counts(db, principal),
        next_before=items[-1].created_at if len(rows) > limit else None,
    )


def csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # Excel исполняет ячейки, начинающиеся с этих знаков, как формулы.
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def items_text(items: list[Any]) -> str:
    parts = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("sku") or "товар"
            parts.append(f"{name} × {item.get('qty', 1)}")
    return ", ".join(parts)


def when(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


@router.get("/export")
async def export_leads(
    principal: Owner,
    db: TenantDb,
    status_: Annotated[LeadStatus | None, Query(alias="status")] = None,
    assignee: Annotated[str | None, Query(max_length=36)] = None,
    channel: ChannelType | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    query = filtered(principal, status_, assignee, channel, q, due=False)
    rows = (await db.execute(query.order_by(Lead.created_at.desc()).limit(EXPORT_LIMIT))).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "Номер",
            "Создана (UTC)",
            "Статус",
            "Имя",
            "Телефон",
            "Канал",
            "Сумма, ₸",
            "Товары",
            "Адрес",
            "Доставка (UTC)",
            "Ответственный",
            "Причина отказа",
            "Напомнить (UTC)",
            "Заметка",
        ]
    )
    for lead, channel_type, _tags, assignee_name in rows:
        cells = [
            lead_number(lead.id),
            when(lead.created_at),
            STATUS_RU.get(lead.status, lead.status),
            lead.contact_name,
            lead.contact_phone,
            channel_type,
            lead.total_kzt,
            items_text(lead.items),
            lead.address,
            when(lead.delivery_at),
            assignee_name,
            REASON_RU.get(lead.cancel_reason or "", ""),
            when(lead.remind_at),
            lead.note,
        ]
        writer.writerow([csv_cell(cell) for cell in cells])
    log.info("leads.exported", tenant_id=str(principal.tenant_id), rows=len(rows))
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="leads.csv"',
            "Cache-Control": "no-store",
        },
    )


def apply_status(lead: Lead, new_status: str) -> None:
    lead.status = new_status
    if new_status != "cancelled":
        lead.cancel_reason = None
    if new_status not in OPEN:
        lead.remind_at = None


@router.post("/bulk")
async def bulk_update(body: BulkIn, principal: Member, db: TenantDb) -> BulkOut:
    changes = body.model_fields_set - {"ids"}
    if not changes or ("status" in changes and body.status is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing_to_update")
    values: dict[str, Any] = {}
    if "assignee_id" in changes:
        if body.assignee_id:
            await ensure_member(db, body.assignee_id)
        values["assignee_id"] = body.assignee_id
    if body.status:
        values["status"] = body.status
        if body.status != "cancelled":
            values["cancel_reason"] = None
        if body.status not in OPEN:
            values["remind_at"] = None
    result = await db.execute(update(Lead).where(Lead.id.in_(body.ids)).values(**values))
    await poke(principal.tenant_id)
    return BulkOut(updated=int(getattr(result, "rowcount", 0) or 0))


@router.patch("/{lead_id}")
async def update_lead(lead_id: uuid.UUID, body: LeadIn, principal: Member, db: TenantDb) -> LeadOut:
    lead = await db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead_not_found")
    fields = body.model_fields_set
    if body.status:
        apply_status(lead, body.status)
    if "assignee_id" in fields:
        if body.assignee_id:
            await ensure_member(db, body.assignee_id)
        lead.assignee_id = body.assignee_id
    if "cancel_reason" in fields:
        if body.cancel_reason and lead.status != "cancelled":
            raise HTTPException(status.HTTP_409_CONFLICT, "lead_not_cancelled")
        lead.cancel_reason = body.cancel_reason
    if "remind_at" in fields:
        if body.remind_at and lead.status not in OPEN:
            raise HTTPException(status.HTTP_409_CONFLICT, "lead_closed")
        lead.remind_at = body.remind_at
    if "note" in fields:
        lead.note = (body.note or "").strip() or None
    await db.flush()
    await poke(principal.tenant_id)
    await db.refresh(lead)
    names = await member_names(db, [lead.assignee_id])
    return lead_out(lead, names.get(lead.assignee_id) if lead.assignee_id else None)
