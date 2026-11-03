from functools import lru_cache

from app.core.config import get_settings
from app.llm.gemini import GeminiLLM
from app.llm.types import LLM, LLMError, LLMResponse, Message, Tool, ToolCall, Usage

__all__ = [
    "LLM",
    "GeminiLLM",
    "LLMError",
    "LLMResponse",
    "Message",
    "Tool",
    "ToolCall",
    "Usage",
    "get_llm",
]


@lru_cache
def get_llm() -> LLM | None:
    settings = get_settings()
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
        return None
    return GeminiLLM(settings)
