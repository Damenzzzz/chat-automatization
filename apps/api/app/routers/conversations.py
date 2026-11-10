import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import case, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.agent.draft import NothingToAnswerError, draft_reply
from app.agent.runtime import Agent, get_agent
from app.auth.deps import CurrentUser, Principal, TenantDb, require_role
from app.channels.outbound import Outbound
from app.channels.registry import get_adapters
from app.channels.types import ChannelError, OutgoingMessage
from app.core.ratelimit import limit
from app.core.redis import get_redis
from app.db.session import tenant_session
from app.llm import LLM, LLMError, get_llm
from app.mlclient import MLClient, get_ml_client
from app.models import Channel, Conversation, Customer, Lead, Message, Product
from app.routers.leads import LeadOut, lead_out

router = APIRouter(prefix="/conversations", tags=["conversations"])
log = structlog.get_logger()

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
Filter = Literal["all", "bot", "human", "leads"]
MAX_MESSAGES = 200
CUSTOMER_LEADS = 5
DRAFTS_PER_HOUR = 60
POLL_SECONDS = 1.5
STREAM_SECONDS = 300
PING_SECONDS = 15


def get_outbound() -> Outbound:
    return Outbound(get_adapters())


class ConversationRow(BaseModel):
    id: uuid.UUID
    channel: str | None
    channel_name: str | None
    customer_name: str | None
    customer_phone: str | None
    mode: str
    status: str
    paused_reason: str | None
    last_message_at: datetime | None
    preview: str | None
    preview_role: str | None
    waiting: bool
    lead_status: str | None


class Counts(BaseModel):
    all: int
    bot: int
    human: int
    leads: int
    waiting: int


class ConversationList(BaseModel):
    items: list[ConversationRow]
    counts: Counts
    next_before: datetime | None


class CardOut(BaseModel):
    id: uuid.UUID
    name: str
    sku: str | None
    price: int | None
    stock: int | None
    image: str | None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str | None
    voice: bool
    created_at: datetime
    delivered: bool | None
    lang: str | None
    intent: str | None
    model: str | None
    latency_ms: int | None
    steps: list[dict[str, Any]]
    cards: list[CardOut]


class LeadBrief(BaseModel):
    id: uuid.UUID
    status: str
    total_kzt: int | None
    created_at: datetime


class CustomerOut(BaseModel):
    id: uuid.UUID
    name: str | None
    phone: str | None
    channel: str
    lang: str | None
    note: str | None
    first_seen_at: datetime
    dialogs: int
    leads: list[LeadBrief]


class ConversationDetail(ConversationRow):
    messages: list[MessageOut]
    leads: list[LeadOut]
    customer: CustomerOut


class CustomerIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class DraftOut(BaseModel):
    text: str
    verified: bool


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def row_query() -> Select[Any]:
    last = (
        select(Message.content.label("content"), Message.role.label("role"))
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .lateral("last_message")
    )
    lead = (
        select(Lead.status.label("status"))
        .where(Lead.conversation_id == Conversation.id)
        .order_by(Lead.created_at.desc())
        .limit(1)
        .lateral("last_lead")
    )
    return (
        select(
            Conversation,
            Customer.name,
            Customer.phone,
            Customer.channel,
            Channel.name,
            last.c.content,
            last.c.role,
            lead.c.status,
        )
        .join(Customer, Customer.id == Conversation.customer_id)
        .outerjoin(Channel, Channel.id == Conversation.channel_id)
        .outerjoin(last, true())
        .outerjoin(lead, true())
        .where(Conversation.sandbox.is_(False))
    )


def row_values(row: Any) -> dict[str, Any]:
    conversation, name, phone, channel, channel_name, content, role, lead_status = row
    return {
        "id": conversation.id,
        "channel": channel,
        "channel_name": channel_name,
        "customer_name": name,
        "customer_phone": phone,
        "mode": conversation.mode,
        "status": conversation.status,
        "paused_reason": conversation.paused_reason,
        "last_message_at": conversation.last_message_at,
        "preview": content,
        "preview_role": role,
        "waiting": conversation.mode == "human" and role == "customer",
        "lead_status": lead_status,
    }


async def conversation_counts(db: AsyncSession) -> Counts:
    has_lead = (
        select(Lead.id)
        .where(Lead.conversation_id == Conversation.id)
        .exists()
        .correlate(Conversation)
    )
    last_role = (
        select(Message.role)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .scalar_subquery()
        .correlate(Conversation)
    )
    row = (
        await db.execute(
            select(
                func.count(),
                func.count(case((Conversation.mode == "bot", 1))),
                func.count(case((Conversation.mode == "human", 1))),
                func.count(case((has_lead, 1))),
                func.count(case(((Conversation.mode == "human") & (last_role == "customer"), 1))),
            ).where(Conversation.sandbox.is_(False))
        )
    ).one()
    return Counts(all=row[0], bot=row[1], human=row[2], leads=row[3], waiting=row[4])


def matches(q: str) -> Any:
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    digits = "".join(ch for ch in q if ch.isdigit())
    found = [
        Customer.name.ilike(like),
        select(Message.id)
        .where(Message.conversation_id == Conversation.id, Message.content.ilike(like))
        .exists(),
    ]
    if len(digits) >= 3:
        found.append(Customer.phone.like(f"%{digits}%"))
    return or_(*found)


@router.get("")
async def list_conversations(
    principal: Member,
    db: TenantDb,
    filter_: Annotated[Filter, Query(alias="filter")] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: datetime | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> ConversationList:
    query = row_query().where(Conversation.last_message_at.is_not(None))
    if q and q.strip():
        query = query.where(matches(q.strip()))
    if filter_ in ("bot", "human"):
        query = query.where(Conversation.mode == filter_)
    elif filter_ == "leads":
        query = query.where(select(Lead.id).where(Lead.conversation_id == Conversation.id).exists())
    if before:
        query = query.where(Conversation.last_message_at < before)
    rows = (
        await db.execute(query.order_by(Conversation.last_message_at.desc()).limit(limit + 1))
    ).all()
    items = [ConversationRow(**row_values(row)) for row in rows[:limit]]
    return ConversationList(
        items=items,
        counts=await conversation_counts(db),
        next_before=items[-1].last_message_at if len(rows) > limit else None,
    )


async def stream_changes(
    tenant_id: uuid.UUID,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    poll_seconds: float = POLL_SECONDS,
    max_seconds: float = STREAM_SECONDS,
) -> AsyncGenerator[str]:
    async with tenant_session(tenant_id) as session:
        since = await session.scalar(select(func.now()))
    deadline = time.monotonic() + max_seconds
    pinged = time.monotonic()
    yield "retry: 3000\n\n"
    while time.monotonic() < deadline and not await is_disconnected():
        await asyncio.sleep(poll_seconds)
        async with tenant_session(tenant_id) as session:
            rows = (
                await session.execute(
                    select(Conversation.id, Conversation.updated_at).where(
                        Conversation.updated_at > since, Conversation.sandbox.is_(False)
                    )
                )
            ).all()
            leads = (
                await session.execute(
                    select(Lead.conversation_id, Lead.updated_at).where(Lead.updated_at > since)
                )
            ).all()
        if rows or leads:
            since = max(moment for _, moment in [*rows, *leads])
            ids = sorted({str(i) for i, _ in [*rows, *leads] if i})
            data = json.dumps({"conversations": ids, "leads": bool(leads)})
            yield f"event: change\ndata: {data}\n\n"
            pinged = time.monotonic()
        elif time.monotonic() - pinged > PING_SECONDS:
            yield ": ping\n\n"
            pinged = time.monotonic()


@router.get("/stream")
async def stream(request: Request, principal: CurrentUser) -> StreamingResponse:
    return StreamingResponse(
        stream_changes(principal.tenant_id, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


async def load_row(db: AsyncSession, conversation_id: uuid.UUID) -> Any:
    row = (await db.execute(row_query().where(Conversation.id == conversation_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation_not_found")
    return row


def message_out(message: Message, products: dict[str, Product]) -> MessageOut:
    trace = message.trace or {}
    steps = list(trace.get("steps", []))
    send = next((s for s in steps if s.get("node") in ("send", "manager")), None)
    cards = [
        CardOut(
            id=p.id,
            name=p.name,
            sku=p.sku,
            price=p.price,
            stock=p.stock,
            image=next((url for url in p.images if url.startswith("https://")), None),
        )
        for p in (products[i] for i in (send or {}).get("products", []) if i in products)
    ]
    media = (message.media or {}).get("items", [])
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        voice=any(item.get("kind") == "audio" for item in media),
        created_at=message.created_at,
        delivered=send.get("delivered") if send else None,
        lang=trace.get("lang"),
        intent=trace.get("intent"),
        model=message.model,
        latency_ms=message.latency_ms,
        steps=steps,
        cards=cards,
    )


async def load_products(db: AsyncSession, messages: list[Message]) -> dict[str, Product]:
    ids = {
        uuid.UUID(product_id)
        for message in messages
        for step in (message.trace or {}).get("steps", [])
        if step.get("node") == "send"
        for product_id in step.get("products", [])
    }
    if not ids:
        return {}
    rows = await db.scalars(select(Product).where(Product.id.in_(ids)))
    return {str(p.id): p for p in rows}


async def detail(db: AsyncSession, conversation_id: uuid.UUID) -> ConversationDetail:
    row = await load_row(db, conversation_id)
    messages = list(
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(MAX_MESSAGES)
        )
    )
    messages.reverse()
    products = await load_products(db, messages)
    leads = await db.scalars(
        select(Lead).where(Lead.conversation_id == conversation_id).order_by(Lead.created_at.desc())
    )
    return ConversationDetail(
        **row_values(row),
        messages=[message_out(m, products) for m in messages],
        leads=[lead_out(lead) for lead in leads],
        customer=await customer_out(db, row[0].customer_id),
    )


async def customer_out(db: AsyncSession, customer_id: uuid.UUID) -> CustomerOut:
    customer = await db.get(Customer, customer_id)
    assert customer is not None  # noqa: S101
    own = select(Conversation.id).where(
        Conversation.customer_id == customer_id, Conversation.sandbox.is_(False)
    )
    dialogs = await db.scalar(select(func.count()).select_from(own.subquery()))
    leads = await db.scalars(
        select(Lead)
        .where(Lead.conversation_id.in_(own))
        .order_by(Lead.created_at.desc())
        .limit(CUSTOMER_LEADS)
    )
    return CustomerOut(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        channel=customer.channel,
        lang=customer.lang,
        note=customer.note,
        first_seen_at=customer.created_at,
        dialogs=int(dialogs or 0),
        leads=[
            LeadBrief(id=x.id, status=x.status, total_kzt=x.total_kzt, created_at=x.created_at)
            for x in leads
        ],
    )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, principal: Member, db: TenantDb
) -> ConversationDetail:
    return await detail(db, conversation_id)


async def set_mode(db: AsyncSession, conversation_id: uuid.UUID, mode: str) -> None:
    row = await load_row(db, conversation_id)
    conversation: Conversation = row[0]
    conversation.mode = mode
    conversation.paused_reason = None
    await db.flush()


@router.post("/{conversation_id}/takeover")
async def takeover(conversation_id: uuid.UUID, principal: Member, db: TenantDb) -> ConversationRow:
    await set_mode(db, conversation_id, "human")
    return ConversationRow(**row_values(await load_row(db, conversation_id)))


@router.post("/{conversation_id}/release")
async def release(conversation_id: uuid.UUID, principal: Member, db: TenantDb) -> ConversationRow:
    await set_mode(db, conversation_id, "bot")
    return ConversationRow(**row_values(await load_row(db, conversation_id)))


@router.post("/{conversation_id}/reply", status_code=status.HTTP_201_CREATED)
async def reply(
    conversation_id: uuid.UUID,
    body: ReplyIn,
    principal: Member,
    db: TenantDb,
    outbound: Annotated[Outbound, Depends(get_outbound)],
    agent: Annotated[Agent, Depends(get_agent)],
) -> MessageOut:
    row = await load_row(db, conversation_id)
    conversation: Conversation = row[0]
    if conversation.channel_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "channel_missing")
    external_id = await db.scalar(
        select(Customer.external_id).where(Customer.id == conversation.customer_id)
    )
    assert external_id is not None  # noqa: S101
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "reply_empty")
    step: dict[str, Any] = {"node": "manager", "user_id": str(principal.user_id)}
    try:
        await outbound.send(conversation.channel_id, external_id, OutgoingMessage(text=text))
        step["delivered"] = True
    except ChannelError as exc:
        log.warning("manager.send_failed", conversation_id=str(conversation_id), error=str(exc))
        step |= {"delivered": False, "error": str(exc)}
    message = Message(
        tenant_id=principal.tenant_id,
        conversation_id=conversation_id,
        role="manager",
        content=text,
        trace={"steps": [step]},
    )
    db.add(message)
    await db.flush()
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(mode="human", paused_reason=None, last_message_at=func.now())
    )
    await db.refresh(message)
    if step["delivered"]:
        await agent.remember_manager_reply(conversation_id, text)
    return message_out(message, {})


@router.patch("/{conversation_id}/customer")
async def update_customer(
    conversation_id: uuid.UUID, body: CustomerIn, principal: Member, db: TenantDb
) -> CustomerOut:
    row = await load_row(db, conversation_id)
    customer = await db.get(Customer, row[0].customer_id)
    assert customer is not None  # noqa: S101
    customer.note = (body.note or "").strip() or None
    await db.flush()
    return await customer_out(db, customer.id)


@router.post("/{conversation_id}/draft")
async def draft(
    conversation_id: uuid.UUID,
    principal: Member,
    db: TenantDb,
    redis: Annotated[Redis, Depends(get_redis)],
    llm: Annotated[LLM | None, Depends(get_llm)],
    ml: Annotated[MLClient, Depends(get_ml_client)],
) -> DraftOut:
    await load_row(db, conversation_id)
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "llm_unavailable")
    await limit(redis, f"draft:{principal.tenant_id}", DRAFTS_PER_HOUR, 3600)
    try:
        result = await draft_reply(db, principal.tenant_id, conversation_id, llm, ml)
    except NothingToAnswerError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "nothing_to_answer") from exc
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "llm_failed") from exc
    return DraftOut(text=result.text, verified=result.verified)
