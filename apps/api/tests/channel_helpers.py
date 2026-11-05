import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.channels.types import (
    ChannelConfig,
    ChannelError,
    CheckResult,
    IncomingMessage,
    Media,
    OutgoingMessage,
)
from app.core.crypto import encrypt_json


async def make_channel(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    *,
    type_: str = "telegram",
    status: str = "active",
    secret: str | None = "secret",  # noqa: S107
    credentials: dict[str, str] | None = None,
    public_key: str | None = None,
    domain: str | None = None,
) -> uuid.UUID:
    async with engine.begin() as conn:
        channel_id: uuid.UUID = await conn.scalar(
            text(
                "INSERT INTO channels (tenant_id, type, status, webhook_secret, credentials_enc,"
                " public_key, domain) VALUES (:t, :type, :status, :secret, :creds, :key, :domain)"
                " RETURNING id"
            ),
            {
                "t": tenant_id,
                "type": type_,
                "status": status,
                "secret": secret,
                "creds": encrypt_json(credentials) if credentials else None,
                "key": public_key,
                "domain": domain,
            },
        )
    return channel_id


def incoming(
    channel_id: uuid.UUID,
    external_id: str,
    message: str = "привет",
    *,
    customer: str = "c1",
    media: list[Media] | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        channel_id=channel_id,
        external_id=external_id,
        customer_external_id=customer,
        text=message,
        media=media or [],
        received_at=datetime(2026, 11, 5, tzinfo=UTC),
    )


class RecordingAdapter:
    type = "telegram"

    def __init__(self, *, fail: bool = False, audio: bytes = b"voice") -> None:
        self.fail = fail
        self.audio = audio
        self.sent: list[tuple[str, OutgoingMessage]] = []
        self.acked: list[str] = []
        self.downloaded: list[str] = []

    def parse(self, channel: ChannelConfig, payload: dict[str, Any]) -> list[IncomingMessage]:
        return []

    async def send(
        self, channel: ChannelConfig, customer_external_id: str, message: OutgoingMessage
    ) -> None:
        if self.fail:
            raise ChannelError("сеть недоступна")
        self.sent.append((customer_external_id, message))

    async def download(self, channel: ChannelConfig, media: Media) -> bytes:
        if self.fail:
            raise ChannelError("сеть недоступна")
        self.downloaded.append(media.file_id)
        return self.audio

    async def acknowledge(self, channel: ChannelConfig, message: IncomingMessage) -> None:
        self.acked.append(message.external_id)

    async def check(self, channel: ChannelConfig) -> CheckResult:
        return CheckResult(ok=True, display_name="bot")
