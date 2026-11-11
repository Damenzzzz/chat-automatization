import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.deps import Principal, TenantDb, require_role
from app.core.poke import poke
from app.models import Conversation, Customer, Lead

router = APIRouter(prefix="/leads", tags=["leads"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
LeadStatus = Literal["new", "in_progress", "done", "cancelled"]


class LeadOut(BaseModel):
    id: uuid.UUID
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
    created_at: datetime


class LeadRow(LeadOut):
    channel: str | None


class LeadList(BaseModel):
    items: list[LeadRow]
    next_before: datetime | None


class LeadStatusIn(BaseModel):
    status: LeadStatus


def lead_out(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id,
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
        created_at=lead.created_at,
    )


@router.get("")
async def list_leads(
    principal: Member,
    db: TenantDb,
    status_: Annotated[LeadStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: datetime | None = None,
) -> LeadList:
    query = (
        select(Lead, Customer.channel)
        .outerjoin(Conversation, Conversation.id == Lead.conversation_id)
        .outerjoin(Customer, Customer.id == Conversation.customer_id)
    )
    if status_:
        query = query.where(Lead.status == status_)
    if before:
        query = query.where(Lead.created_at < before)
    rows = (await db.execute(query.order_by(Lead.created_at.desc()).limit(limit + 1))).all()
    items = [LeadRow(**lead_out(lead).model_dump(), channel=ch) for lead, ch in rows[:limit]]
    return LeadList(items=items, next_before=items[-1].created_at if len(rows) > limit else None)


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: uuid.UUID, body: LeadStatusIn, principal: Member, db: TenantDb
) -> LeadOut:
    lead = await db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead_not_found")
    lead.status = body.status
    await db.flush()
    await poke(principal.tenant_id)
    await db.refresh(lead)
    return lead_out(lead)
