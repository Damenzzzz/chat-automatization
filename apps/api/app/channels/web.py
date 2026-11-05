import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from app.channels.outgoing import button_text
from app.channels.types import (
    ChannelConfig,
    ChannelError,
    CheckResult,
    IncomingMessage,
    Media,
    OutgoingMessage,
)
from app.core.redis import get_redis

STREAM_MAX_EVENTS = 100
STREAM_TTL = 3600


def customer_id(session: str) -> str:
    return hashlib.sha256(session.encode()).hexdigest()[:40]


def stream_key(channel_id: Any, customer: str) -> str:
    return f"widget:{channel_id}:{customer}"


def origin_allowed(domain: str | None, origin: str | None) -> bool:
    if not domain or not origin:
        return False
    try:
        host = urlsplit(origin).hostname
    except ValueError:
        return False
    if not host:
        return False
    bare = domain.removeprefix("www.")
    return host.lower() in (bare, f"www.{bare}")


class WebAdapter:
    type = "web"

    def parse(self, channel: ChannelConfig, payload: dict[str, Any]) -> list[IncomingMessage]:
        customer = customer_id(payload["session"])
        pressed = payload.get("payload")
        text = button_text(pressed) if pressed else str(payload.get("text") or "").strip()
        if not text:
            return []
        return [
            IncomingMessage(
                channel_id=channel.id,
                external_id=f"{customer}:{payload['id']}",
                customer_external_id=customer,
                text=text,
                received_at=datetime.now(UTC),
            )
        ]

    async def send(
        self, channel: ChannelConfig, customer_external_id: str, message: OutgoingMessage
    ) -> None:
        redis: Any = get_redis()
        key = stream_key(channel.id, customer_external_id)
        pipe = redis.pipeline(transaction=True)
        pipe.xadd(
            key, {"data": message.model_dump_json()}, maxlen=STREAM_MAX_EVENTS, approximate=True
        )
        pipe.expire(key, STREAM_TTL)
        await pipe.execute()

    async def download(self, channel: ChannelConfig, media: Media) -> bytes:
        raise ChannelError("web: у виджета нет вложений")

    async def acknowledge(self, channel: ChannelConfig, message: IncomingMessage) -> None:
        return None

    async def check(self, channel: ChannelConfig) -> CheckResult:
        return CheckResult(ok=True, display_name=channel.domain)
