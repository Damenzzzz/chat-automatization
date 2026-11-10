import secrets
import uuid
from collections.abc import Mapping
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompt import money
from app.billing.ledger import Charge
from app.channels.store import load_channel
from app.channels.types import ChannelAdapter, ChannelError, OutgoingMessage
from app.db.session import tenant_session
from app.models import Channel, LedgerEntry, Notification, User

log = structlog.get_logger()

NOTIFY_OWNER = "notify_owner"
THRESHOLDS = (20, 5, 0)
LINK_TTL = 600
LINK_PREFIX = "owner_"


def crossed_threshold(before: int, after: int, last_topup: int) -> int | None:
    crossed = [t for t in THRESHOLDS if before * 100 > t * last_topup >= after * 100]
    return min(crossed) if crossed else None


def alert_text(threshold: int, balance: int, last_topup: int) -> str:
    if threshold == 0:
        return (
            "Баланс Satushy закончился: бот передаёт диалоги менеджеру и отвечает шаблоном."
            " Пополните баланс, чтобы бот снова заработал."
        )
    return (
        f"На балансе Satushy осталось {money(balance)}: это меньше {threshold}%"
        f" от последнего пополнения ({money(last_topup)}). Пополните баланс заранее."
    )


async def balance_alert(session: AsyncSession, tenant_id: uuid.UUID, charge: Charge) -> str | None:
    last_topup = await session.scalar(
        select(LedgerEntry.amount_kzt)
        .where(LedgerEntry.type == "topup")
        .order_by(LedgerEntry.created_at.desc())
        .limit(1)
    )
    if not last_topup:
        return None
    threshold = crossed_threshold(charge.balance_before, charge.balance_after, last_topup)
    if threshold is None:
        return None
    text = alert_text(threshold, charge.balance_after, last_topup)
    session.add(
        Notification(
            tenant_id=tenant_id,
            kind="balance_low" if threshold else "balance_zero",
            text=text,
            details={
                "threshold": threshold,
                "balance_kzt": charge.balance_after,
                "last_topup_kzt": last_topup,
            },
        )
    )
    return text


async def send_owner_message(
    tenant_id: uuid.UUID,
    text: str,
    adapters: Mapping[str, ChannelAdapter],
    roles: tuple[str, ...] = ("owner",),
) -> int:
    async with tenant_session(tenant_id) as session:
        channel_id = await session.scalar(
            select(Channel.id)
            .where(Channel.type == "telegram", Channel.status == "active")
            .order_by(Channel.created_at)
            .limit(1)
        )
        chats = list(
            await session.scalars(
                select(User.telegram_chat_id).where(
                    User.role.in_(roles), User.is_active, User.telegram_chat_id.is_not(None)
                )
            )
        )
    channel = await load_channel(channel_id) if channel_id else None
    if channel is None or not chats:
        return 0
    sent = 0
    for chat in chats:
        try:
            await adapters["telegram"].send(channel, str(chat), OutgoingMessage(text=text))
            sent += 1
        except ChannelError as exc:
            log.warning("billing.owner_alert_failed", tenant_id=str(tenant_id), error=str(exc))
    return sent


def new_link_token() -> str:
    return LINK_PREFIX + secrets.token_urlsafe(16)


def link_key(token: str) -> str:
    return f"owner-link:{token}"


async def create_owner_link(redis: Any, tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
    token = new_link_token()
    await redis.set(link_key(token), f"{tenant_id}:{user_id}", ex=LINK_TTL)
    return token


def owner_link_token(payload: dict[str, Any]) -> tuple[str, str] | None:
    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    text = str(message.get("text") or "")
    if chat.get("type") != "private" or not text.startswith(f"/start {LINK_PREFIX}"):
        return None
    return text.removeprefix("/start ").strip(), str(chat["id"])


async def link_owner(redis: Any, channel_tenant: uuid.UUID, token: str, chat_id: str) -> bool:
    value = await redis.getdel(link_key(token))
    if not value:
        return False
    tenant, user = value.split(":")
    if uuid.UUID(tenant) != channel_tenant:
        return False
    async with tenant_session(channel_tenant) as session:
        await session.execute(
            update(User).where(User.id == uuid.UUID(user)).values(telegram_chat_id=chat_id)
        )
    return True
