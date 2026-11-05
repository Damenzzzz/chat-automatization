from functools import lru_cache

from app.channels.telegram import TelegramAdapter
from app.channels.types import ChannelAdapter
from app.channels.web import WebAdapter
from app.channels.whatsapp import WhatsAppAdapter


@lru_cache
def get_adapters() -> dict[str, ChannelAdapter]:
    return {"telegram": TelegramAdapter(), "whatsapp": WhatsAppAdapter(), "web": WebAdapter()}
