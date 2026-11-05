from functools import lru_cache

from app.channels.telegram import TelegramAdapter
from app.channels.types import ChannelAdapter


@lru_cache
def get_adapters() -> dict[str, ChannelAdapter]:
    return {"telegram": TelegramAdapter()}
