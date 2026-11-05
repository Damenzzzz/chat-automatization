import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

ChannelType = Literal["telegram", "whatsapp", "web", "instagram"]


class ChannelError(Exception):
    pass


class Media(BaseModel):
    kind: Literal["audio"] = "audio"
    file_id: str
    mime_type: str | None = None
    size: int | None = None


class IncomingMessage(BaseModel):
    channel_id: uuid.UUID
    external_id: str
    customer_external_id: str
    text: str = ""
    media: list[Media] = Field(default_factory=list)
    received_at: datetime
    customer_name: str | None = None


class Button(BaseModel):
    title: str
    payload: str


class ProductCard(BaseModel):
    title: str
    caption: str
    image_url: str | None = None
    buttons: list[Button] = Field(default_factory=list)


class OutgoingMessage(BaseModel):
    text: str = ""
    cards: list[ProductCard] = Field(default_factory=list)
    buttons: list[Button] = Field(default_factory=list)


@dataclass(frozen=True)
class ChannelConfig:
    id: uuid.UUID
    tenant_id: uuid.UUID
    type: str
    status: str
    webhook_secret: str | None = None
    domain: str | None = None
    credentials: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    display_name: str | None = None
    error: str | None = None


class ChannelAdapter(Protocol):
    type: str

    def parse(self, channel: ChannelConfig, payload: dict[str, Any]) -> list[IncomingMessage]: ...

    async def send(
        self, channel: ChannelConfig, customer_external_id: str, message: OutgoingMessage
    ) -> None: ...

    async def download(self, channel: ChannelConfig, media: Media) -> bytes: ...

    async def acknowledge(self, channel: ChannelConfig, message: IncomingMessage) -> None: ...

    async def check(self, channel: ChannelConfig) -> CheckResult: ...
