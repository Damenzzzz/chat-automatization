import uuid
from collections.abc import Mapping

import structlog

from app.channels.store import load_channel
from app.channels.types import (
    ChannelAdapter,
    ChannelConfig,
    ChannelError,
    IncomingMessage,
    Media,
    OutgoingMessage,
)

log = structlog.get_logger()


class Outbound:
    def __init__(self, adapters: Mapping[str, ChannelAdapter]) -> None:
        self.adapters = adapters

    async def _resolve(self, channel_id: uuid.UUID) -> tuple[ChannelConfig, ChannelAdapter]:
        channel = await load_channel(channel_id)
        if channel is None:
            raise ChannelError("канал не найден")
        adapter = self.adapters.get(channel.type)
        if adapter is None:
            raise ChannelError(f"нет адаптера для канала {channel.type}")
        return channel, adapter

    async def send(
        self, channel_id: uuid.UUID, customer_external_id: str, message: OutgoingMessage
    ) -> None:
        channel, adapter = await self._resolve(channel_id)
        await adapter.send(channel, customer_external_id, message)

    async def download(self, channel_id: uuid.UUID, media: Media) -> bytes:
        channel, adapter = await self._resolve(channel_id)
        return await adapter.download(channel, media)

    async def acknowledge(self, channel_id: uuid.UUID, message: IncomingMessage) -> None:
        try:
            channel, adapter = await self._resolve(channel_id)
            await adapter.acknowledge(channel, message)
        except ChannelError as exc:
            log.warning("channel.ack_failed", channel_id=str(channel_id), error=str(exc))
