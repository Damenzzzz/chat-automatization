import re
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from redis.asyncio import Redis

from app.channels.http import read_body
from app.channels.registry import get_adapters
from app.channels.store import load_channel_by_key
from app.channels.types import ChannelAdapter, ChannelConfig
from app.channels.web import (
    customer_id,
    new_session,
    origin_allowed,
    session_valid,
    stream_key,
)
from app.core.config import get_settings
from app.core.net import client_ip
from app.core.ratelimit import limit
from app.core.redis import get_redis
from app.routers.webhooks import GatewayDep

router = APIRouter(prefix="/widget", tags=["widget"])

SESSION = re.compile(r"^[A-Za-z0-9_-]{22,48}\.[A-Za-z0-9_-]{22}$")
EVENT_ID = re.compile(r"^\d+-\d+$")
MAX_BODY = 16 * 1024
SESSION_PER_MINUTE = 20
IP_PER_MINUTE = 60
SSE_BLOCK_MS = 15_000
SSE_MAX_SECONDS = 300

RedisDep = Annotated[Redis, Depends(get_redis)]
AdaptersDep = Annotated[dict[str, ChannelAdapter], Depends(get_adapters)]
OriginHeader = Annotated[str | None, Header(alias="Origin")]
SessionHeader = Annotated[str | None, Header(alias="X-Widget-Session")]


class WidgetMessageIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    text: str | None = Field(default=None, max_length=2000)
    payload: str | None = Field(default=None, max_length=64)


def cors_headers(origin: str) -> dict[str, str]:
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}


async def widget_channel(public_key: str, origin: OriginHeader = None) -> ChannelConfig:
    channel = await load_channel_by_key(public_key)
    if channel is None or channel.type != "web" or channel.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "widget_not_found")
    if not origin_allowed(channel.domain, origin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin_not_allowed")
    return channel


ChannelDep = Annotated[ChannelConfig, Depends(widget_channel)]


def client_session(session: str | None, origin: str) -> str:
    if not session or not SESSION.match(session) or not session_valid(session):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "session_invalid", headers=cors_headers(origin)
        )
    return session


async def enforce_limit(redis: Any, key: str, count: int, origin: str, window: int = 60) -> None:
    await limit(redis, key, count, window, cors_headers(origin))


@router.options("/{public_key}/{path}", include_in_schema=False)
async def preflight(channel: ChannelDep, origin: OriginHeader = None) -> Response:
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={
            **cors_headers(origin or ""),
            "Access-Control-Allow-Methods": "GET, POST",
            "Access-Control-Allow-Headers": "Content-Type, X-Widget-Session, Last-Event-ID",
            "Access-Control-Max-Age": "600",
        },
    )


@router.post("/{public_key}/session")
async def open_session(
    request: Request, channel: ChannelDep, redis: RedisDep, origin: OriginHeader = None
) -> JSONResponse:
    origin = origin or ""
    per_hour = get_settings().widget_sessions_per_ip_hour
    key = f"widget-new:{channel.id}:{client_ip(request)}"
    await enforce_limit(redis, key, per_hour, origin, 3600)
    return JSONResponse({"session": new_session()}, headers=cors_headers(origin))


@router.post("/{public_key}/messages")
async def post_message(
    request: Request,
    channel: ChannelDep,
    gateway: GatewayDep,
    adapters: AdaptersDep,
    redis: RedisDep,
    origin: OriginHeader = None,
    session: SessionHeader = None,
) -> JSONResponse:
    origin = origin or ""
    token = client_session(session, origin)
    client = client_ip(request)
    await enforce_limit(redis, f"widget-ip:{channel.id}:{client}", IP_PER_MINUTE, origin)
    per_hour = get_settings().widget_channel_messages_per_hour
    await enforce_limit(redis, f"widget-channel:{channel.id}", per_hour, origin, 3600)
    await enforce_limit(redis, f"widget-session:{customer_id(token)}", SESSION_PER_MINUTE, origin)
    try:
        body = WidgetMessageIn.model_validate_json(await read_body(request, MAX_BODY))
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "message_invalid", headers=cors_headers(origin)
        ) from exc
    messages = adapters["web"].parse(channel, {"session": token, **body.model_dump()})
    if not messages:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "message_empty", headers=cors_headers(origin)
        )
    accepted = await gateway.accept(channel, messages[0])
    return JSONResponse(
        {"accepted": accepted},
        status_code=status.HTTP_202_ACCEPTED,
        headers=cors_headers(origin),
    )


async def event_stream(redis: Any, key: str, last_id: str, request: Request) -> AsyncIterator[str]:
    deadline = time.monotonic() + SSE_MAX_SECONDS
    yield "retry: 3000\n\n"
    while time.monotonic() < deadline and not await request.is_disconnected():
        rows = await redis.xread({key: last_id}, count=20, block=SSE_BLOCK_MS)
        if not rows:
            yield ": ping\n\n"
            continue
        for _, entries in rows:
            for event_id, fields in entries:
                last_id = event_id
                yield f"id: {event_id}\nevent: message\ndata: {fields['data']}\n\n"


@router.get("/{public_key}/stream")
async def stream(
    request: Request,
    channel: ChannelDep,
    redis: RedisDep,
    origin: OriginHeader = None,
    session: SessionHeader = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    origin = origin or ""
    token = client_session(session, origin)
    client = client_ip(request)
    await enforce_limit(redis, f"widget-stream:{channel.id}:{client}", IP_PER_MINUTE, origin)
    start = last_event_id if last_event_id and EVENT_ID.match(last_event_id) else "0"
    return StreamingResponse(
        event_stream(redis, stream_key(channel.id, customer_id(token)), start, request),
        media_type="text/event-stream",
        headers={
            **cors_headers(origin),
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
