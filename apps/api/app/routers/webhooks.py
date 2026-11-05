import json
import secrets
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from redis.asyncio import Redis

from app.channels.gateway import Gateway
from app.channels.http import read_body
from app.channels.registry import get_adapters
from app.channels.store import load_channel
from app.channels.types import ChannelAdapter, ChannelConfig, IncomingMessage
from app.core.queue import Queue, get_queue
from app.core.redis import get_redis

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = structlog.get_logger()


def get_gateway(
    redis: Annotated[Redis, Depends(get_redis)], queue: Annotated[Queue, Depends(get_queue)]
) -> Gateway:
    return Gateway(redis, queue)


GatewayDep = Annotated[Gateway, Depends(get_gateway)]
AdaptersDep = Annotated[dict[str, ChannelAdapter], Depends(get_adapters)]


async def channel_of_type(channel_id: uuid.UUID, type_: str) -> ChannelConfig:
    channel = await load_channel(channel_id)
    if channel is None or channel.type != type_:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel_not_found")
    return channel


def parse_payload(
    adapter: ChannelAdapter, channel: ChannelConfig, body: bytes
) -> list[IncomingMessage]:
    try:
        payload: dict[str, Any] = json.loads(body)
        return adapter.parse(channel, payload)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        # платформа ретраит не-2xx бесконечно, а этот запрос не станет лучше
        log.warning("channel.bad_payload", channel_id=str(channel.id), error=type(exc).__name__)
        return []


async def accept_all(
    gateway: Gateway, channel: ChannelConfig, messages: list[IncomingMessage]
) -> None:
    if channel.status == "disabled":
        return
    for message in messages:
        await gateway.accept(channel, message)


@router.post("/telegram/{channel_id}")
async def telegram_webhook(
    channel_id: uuid.UUID,
    request: Request,
    gateway: GatewayDep,
    adapters: AdaptersDep,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, bool]:
    channel = await channel_of_type(channel_id, "telegram")
    expected = channel.webhook_secret
    if not expected or not secret or not secrets.compare_digest(secret, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_secret")
    body = await read_body(request)
    await accept_all(gateway, channel, parse_payload(adapters["telegram"], channel, body))
    return {"ok": True}
