import hashlib
import secrets
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import Principal, TenantDb, require_role
from app.channels.registry import get_adapters
from app.channels.store import load_channel
from app.channels.telegram import TOKEN, TelegramAdapter
from app.channels.types import ChannelAdapter, ChannelError
from app.core.config import get_settings
from app.core.crypto import encrypt_json
from app.models import Channel

router = APIRouter(prefix="/channels", tags=["channels"])

Owner = Annotated[Principal, Depends(require_role("owner"))]
AdaptersDep = Annotated[dict[str, ChannelAdapter], Depends(get_adapters)]


class ChannelOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str | None
    status: str
    last_error: str | None
    webhook_url: str | None = None
    verify_token: str | None = None


class TelegramIn(BaseModel):
    token: SecretStr


class WhatsAppIn(BaseModel):
    phone_number_id: str = Field(pattern=r"^\d{5,32}$")
    waba_id: str = Field(pattern=r"^\d{5,32}$")
    access_token: SecretStr = Field(min_length=20, max_length=1024)
    app_secret: SecretStr = Field(min_length=16, max_length=256)


class CheckOut(BaseModel):
    ok: bool
    display_name: str | None = None
    error: str | None = None


def webhook_url(channel: Channel) -> str | None:
    if channel.type not in ("telegram", "whatsapp"):
        return None
    base = get_settings().public_api_url.rstrip("/")
    return f"{base}/webhooks/{channel.type}/{channel.id}"


def channel_out(channel: Channel) -> ChannelOut:
    return ChannelOut(
        id=channel.id,
        type=channel.type,
        name=channel.name,
        status=channel.status,
        last_error=channel.last_error,
        webhook_url=webhook_url(channel),
        verify_token=channel.webhook_secret if channel.type == "whatsapp" else None,
    )


async def upsert_channel(
    db: AsyncSession, principal: Principal, type_: str, external_id: str, **values: Any
) -> Channel:
    channel = await db.scalar(
        select(Channel).where(Channel.type == type_, Channel.external_id == external_id)
    )
    if channel is None:
        channel = Channel(tenant_id=principal.tenant_id, type=type_, external_id=external_id)
        db.add(channel)
    for key, value in values.items():
        setattr(channel, key, value)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "channel_in_use") from exc
    return channel


@router.get("")
async def list_channels(principal: Owner, db: TenantDb) -> list[ChannelOut]:
    rows = await db.scalars(select(Channel).order_by(Channel.created_at))
    return [channel_out(c) for c in rows]


@router.post("/telegram", status_code=status.HTTP_201_CREATED)
async def connect_telegram(
    body: TelegramIn, principal: Owner, db: TenantDb, adapters: AdaptersDep
) -> ChannelOut:
    token = body.token.get_secret_value().strip()
    if not TOKEN.match(token):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "telegram_token_invalid")
    if not get_settings().public_api_url.startswith("https://"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "public_url_not_https")
    adapter = adapters["telegram"]
    assert isinstance(adapter, TelegramAdapter)  # noqa: S101
    secret = secrets.token_urlsafe(32)
    try:
        me = await adapter.get_me(token)
        channel = await upsert_channel(
            db,
            principal,
            "telegram",
            str(me["id"]),
            name=f"@{me.get('username')}",
            credentials_enc=encrypt_json({"token": token}),
            webhook_secret=secret,
            status="active",
            last_error=None,
        )
        await adapter.set_webhook(token, webhook_url(channel) or "", secret)
    except ChannelError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "telegram_token_invalid") from exc
    return channel_out(channel)


@router.post("/whatsapp", status_code=status.HTTP_201_CREATED)
async def connect_whatsapp(body: WhatsAppIn, principal: Owner, db: TenantDb) -> ChannelOut:
    # сам phone_number_id хранится только зашифрованным, для уникальности — его хеш
    external_id = hashlib.sha256(body.phone_number_id.encode()).hexdigest()
    existing = await db.scalar(
        select(Channel.webhook_secret).where(
            Channel.type == "whatsapp", Channel.external_id == external_id
        )
    )
    credentials = {
        "phone_number_id": body.phone_number_id,
        "waba_id": body.waba_id,
        "access_token": body.access_token.get_secret_value().strip(),
        "app_secret": body.app_secret.get_secret_value().strip(),
    }
    channel = await upsert_channel(
        db,
        principal,
        "whatsapp",
        external_id,
        credentials_enc=encrypt_json(credentials),
        webhook_secret=existing or secrets.token_urlsafe(32),
        status="pending",
        last_error=None,
    )
    return channel_out(channel)


@router.post("/{channel_id}/check")
async def check_channel(
    channel_id: uuid.UUID, principal: Owner, db: TenantDb, adapters: AdaptersDep
) -> CheckOut:
    row = await db.get(Channel, channel_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel_not_found")
    config = await load_channel(channel_id)
    adapter = adapters.get(row.type)
    if config is None or adapter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel_not_found")
    result = await adapter.check(config)
    if result.ok:
        row.status, row.last_error = "active", None
        row.name = result.display_name or row.name
    else:
        row.status, row.last_error = "error", result.error
    return CheckOut(ok=result.ok, display_name=result.display_name, error=result.error)
