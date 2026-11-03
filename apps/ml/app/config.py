from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Backend = Literal["qwen3", "bge-m3", "fake"]

QUERY_TASK = (
    "Given a shopper's question in Russian or Kazakh, "
    "retrieve matching products from a shop catalog"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    ml_embedder: Backend = "qwen3"
    ml_reranker: Backend = "qwen3"
    ml_device: str = "auto"
    ml_preload: bool = True
    ml_query_task: str = QUERY_TASK

    ml_max_texts: int = 256
    ml_max_text_chars: int = 8000
    ml_embed_batch_size: int = 32
    ml_embed_max_tokens: int = 512
    ml_rerank_max_docs: int = 100
    ml_rerank_batch_size: int = 8
    ml_rerank_max_tokens: int = 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
