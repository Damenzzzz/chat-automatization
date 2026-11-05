import hashlib
import uuid
from contextlib import suppress
from typing import Any

from redis.exceptions import RedisError

from app.channels.types import ChannelConfig, IncomingMessage
from app.core.config import get_settings
from app.core.queue import Queue

FLUSH = "flush_customer"
DEDUP_TTL = 24 * 3600


def customer_key(customer_external_id: str) -> str:
    return hashlib.sha256(customer_external_id.encode()).hexdigest()[:32]


def buffer_key(channel_id: uuid.UUID | str, key: str) -> str:
    return f"inbox:{channel_id}:{key}"


def seq_key(channel_id: uuid.UUID | str, key: str) -> str:
    return f"inbox-seq:{channel_id}:{key}"


class Gateway:
    def __init__(self, redis: Any, queue: Queue) -> None:
        self.redis = redis
        self.queue = queue

    async def accept(self, channel: ChannelConfig, message: IncomingMessage) -> bool:
        dedup = f"dedup:{channel.id}:{message.external_id}"
        if not await self.redis.set(dedup, "1", nx=True, ex=DEDUP_TTL):
            return False
        key = customer_key(message.customer_external_id)
        try:
            pipe = self.redis.pipeline(transaction=True)
            pipe.rpush(buffer_key(channel.id, key), message.model_dump_json())
            pipe.expire(buffer_key(channel.id, key), DEDUP_TTL)
            pipe.incr(seq_key(channel.id, key))
            pipe.expire(seq_key(channel.id, key), DEDUP_TTL)
            _, _, seq, _ = await pipe.execute()
            await self.queue.enqueue(
                FLUSH,
                str(channel.tenant_id),
                str(channel.id),
                key,
                seq,
                defer_by=get_settings().channel_debounce_seconds,
            )
        except Exception:
            with suppress(RedisError):
                await self.redis.delete(dedup)
            raise
        return True
