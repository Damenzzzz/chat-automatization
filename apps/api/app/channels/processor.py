import uuid
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from redis.exceptions import LockError
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.agent.runtime import Agent
from app.agent.tools import NOTIFY
from app.channels.gateway import FLUSH, buffer_key, seq_key
from app.channels.outbound import Outbound
from app.channels.store import load_channel
from app.channels.types import ChannelConfig, ChannelError, IncomingMessage, OutgoingMessage
from app.core.queue import Queue
from app.db.session import tenant_session
from app.models import Conversation, Customer, Message

log = structlog.get_logger()

LOCK_TTL = 600
BUSY_DELAY = 1.0
GIVE_UP_REPLY = (
    "Не получилось ответить сразу, передали ваш вопрос менеджеру."
    " Жауап бере алмадық, сұрағыңызды менеджерге жібердік."
)
Outcome = Literal["superseded", "empty", "skipped", "busy", "done"]


@dataclass(frozen=True)
class MergedMessage:
    text: str
    media: list[dict[str, Any]]
    external_id: str
    customer_external_id: str
    size: int


def merge_messages(batch: list[IncomingMessage]) -> MergedMessage:
    return MergedMessage(
        text="\n".join(m.text for m in batch if m.text),
        media=[item.model_dump() for m in batch for item in m.media],
        external_id=batch[-1].external_id,
        customer_external_id=batch[-1].customer_external_id,
        size=len(batch),
    )


async def open_conversation(channel: ChannelConfig, message: IncomingMessage) -> uuid.UUID:
    async with tenant_session(channel.tenant_id) as session:
        stmt = insert(Customer).values(
            tenant_id=channel.tenant_id,
            channel=channel.type,
            external_id=message.customer_external_id,
            name=message.customer_name,
        )
        await session.execute(
            stmt.on_conflict_do_nothing(
                index_elements=[Customer.tenant_id, Customer.channel, Customer.external_id]
            )
        )
        customer_id = await session.scalar(
            select(Customer.id).where(
                Customer.channel == channel.type,
                Customer.external_id == message.customer_external_id,
            )
        )
        if message.customer_name:
            await session.execute(
                update(Customer)
                .where(
                    Customer.id == customer_id,
                    Customer.name.is_distinct_from(message.customer_name),
                )
                .values(name=message.customer_name)
            )
        await session.execute(
            insert(Conversation)
            .values(tenant_id=channel.tenant_id, customer_id=customer_id, channel_id=channel.id)
            .on_conflict_do_nothing(
                index_elements=[
                    Conversation.tenant_id,
                    Conversation.customer_id,
                    Conversation.channel_id,
                ],
                index_where=text("status = 'open' AND NOT sandbox"),
            )
        )
        conversation_id = await session.scalar(
            select(Conversation.id).where(
                Conversation.customer_id == customer_id,
                Conversation.channel_id == channel.id,
                Conversation.status == "open",
                Conversation.sandbox.is_(False),
            )
        )
    assert conversation_id is not None  # noqa: S101
    return conversation_id


class Processor:
    def __init__(self, redis: Any, queue: Queue, agent: Agent, outbound: Outbound) -> None:
        self.redis = redis
        self.queue = queue
        self.agent = agent
        self.outbound = outbound

    async def flush(self, tenant_id: str, channel_id: str, key: str, seq: int) -> Outcome:
        if int(await self.redis.get(seq_key(channel_id, key)) or 0) != seq:
            return "superseded"
        buffer = buffer_key(channel_id, key)
        head = await self.redis.lindex(buffer, 0)
        if head is None:
            return "empty"
        channel = await load_channel(uuid.UUID(channel_id))
        if channel is None or channel.status == "disabled":
            await self.redis.delete(buffer)
            return "skipped"
        conversation_id = await open_conversation(
            channel, IncomingMessage.model_validate_json(head)
        )
        lock = self.redis.lock(
            f"lock:conversation:{conversation_id}", timeout=LOCK_TTL, blocking=False
        )
        if not await lock.acquire():
            await self.queue.enqueue(FLUSH, tenant_id, channel_id, key, seq, defer_by=BUSY_DELAY)
            return "busy"
        try:
            raw = await self.redis.lrange(buffer, 0, -1)
            if not raw:
                return "empty"
            batch = [IncomingMessage.model_validate_json(item) for item in raw]
            for message in batch:
                await self.outbound.acknowledge(channel.id, message)
            merged = merge_messages(batch)
            turn = await self.agent.run(
                tenant_id=channel.tenant_id,
                conversation_id=conversation_id,
                text=merged.text,
                channel=channel.type,
                channel_id=channel.id,
                customer_external_id=merged.customer_external_id,
                external_id=merged.external_id,
                media=merged.media,
            )
            await self.redis.ltrim(buffer, len(raw), -1)
            if turn.human_mode and turn.reply is None:
                await self.notify(channel, conversation_id, "customer_message")
            log.info(
                "channel.turn",
                channel_id=channel_id,
                conversation_id=str(conversation_id),
                merged=merged.size,
                human_mode=turn.human_mode,
            )
            return "done"
        finally:
            try:
                await lock.release()
            except LockError:
                log.warning("channel.lock_lost", conversation_id=str(conversation_id))

    async def notify(self, channel: ChannelConfig, conversation_id: uuid.UUID, event: str) -> None:
        await self.queue.enqueue(
            NOTIFY,
            str(channel.tenant_id),
            event,
            {"conversation_id": str(conversation_id), "channel": channel.type},
        )

    async def give_up(self, channel_id: str, key: str) -> None:
        buffer = buffer_key(channel_id, key)
        head = await self.redis.lindex(buffer, 0)
        await self.redis.delete(buffer)
        channel = await load_channel(uuid.UUID(channel_id))
        if head is None or channel is None:
            return
        message = IncomingMessage.model_validate_json(head)
        conversation_id = await open_conversation(channel, message)
        delivered = True
        try:
            await self.outbound.send(
                channel.id, message.customer_external_id, OutgoingMessage(text=GIVE_UP_REPLY)
            )
        except ChannelError as exc:
            delivered = False
            log.warning("channel.give_up_send_failed", channel_id=channel_id, error=str(exc))
        async with tenant_session(channel.tenant_id) as session:
            session.add(
                Message(
                    tenant_id=channel.tenant_id,
                    conversation_id=conversation_id,
                    role="bot",
                    content=GIVE_UP_REPLY,
                    trace={
                        "steps": [{"node": "send", "delivered": delivered, "failed_turn": True}]
                    },
                )
            )
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(mode="human", last_message_at=func.now())
            )
        await self.notify(channel, conversation_id, "turn_failed")
