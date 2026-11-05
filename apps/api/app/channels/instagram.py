from typing import Any

from app.channels.types import (
    ChannelConfig,
    ChannelError,
    CheckResult,
    IncomingMessage,
    Media,
    OutgoingMessage,
)

NOT_AVAILABLE = "instagram: канал подключим после App Review"


class InstagramAdapter:
    type = "instagram"

    def parse(self, channel: ChannelConfig, payload: dict[str, Any]) -> list[IncomingMessage]:
        return []

    async def send(
        self, channel: ChannelConfig, customer_external_id: str, message: OutgoingMessage
    ) -> None:
        raise ChannelError(NOT_AVAILABLE)

    async def download(self, channel: ChannelConfig, media: Media) -> bytes:
        raise ChannelError(NOT_AVAILABLE)

    async def acknowledge(self, channel: ChannelConfig, message: IncomingMessage) -> None:
        return None

    async def check(self, channel: ChannelConfig) -> CheckResult:
        return CheckResult(ok=False, error="Instagram подключим после App Review в Meta.")
