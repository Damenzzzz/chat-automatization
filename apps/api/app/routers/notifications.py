import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
from sqlalchemy import select

from app.auth.deps import Principal, TenantDb, require_role
from app.billing.alerts import LINK_TTL, create_owner_link
from app.core.redis import get_redis
from app.models import Channel, Notification

router = APIRouter(tags=["notifications"])

Member = Annotated[Principal, Depends(require_role("owner", "manager"))]
Owner = Annotated[Principal, Depends(require_role("owner"))]


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    text: str
    details: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class TelegramLinkOut(BaseModel):
    url: str
    expires_in: int


@router.get("/notifications")
async def list_notifications(
    principal: Member, db: TenantDb, unread_only: bool = False
) -> list[NotificationOut]:
    query = select(Notification).order_by(Notification.created_at.desc()).limit(100)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    return [NotificationOut.model_validate(n) for n in await db.scalars(query)]


@router.post("/notifications/{notification_id}/read")
async def read_notification(
    notification_id: uuid.UUID, principal: Member, db: TenantDb
) -> NotificationOut:
    notification = await db.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification_not_found")
    notification.read_at = notification.read_at or datetime.now(UTC)
    await db.flush()
    return NotificationOut.model_validate(notification)


@router.post("/me/telegram/link")
async def telegram_link(
    principal: Member, db: TenantDb, redis: Annotated[Redis, Depends(get_redis)]
) -> TelegramLinkOut:
    bot = await db.scalar(
        select(Channel.name)
        .where(Channel.type == "telegram", Channel.status == "active")
        .order_by(Channel.created_at)
        .limit(1)
    )
    if not bot:
        raise HTTPException(status.HTTP_409_CONFLICT, "telegram_not_connected")
    token = await create_owner_link(redis, principal.tenant_id, principal.user_id)
    return TelegramLinkOut(
        url=f"https://t.me/{bot.removeprefix('@')}?start={token}", expires_in=LINK_TTL
    )
