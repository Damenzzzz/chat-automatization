import asyncio
import time
from typing import Any, Literal

import structlog

from app.config import Settings
from app.models.base import Embedder, Kind, Reranker, resolve_device
from app.models.embedders import SentenceTransformerEmbedder, qwen3_query_prompt
from app.models.fake import FakeEmbedder

log = structlog.get_logger()

EMBEDDER_MODELS = {"qwen3": "Qwen/Qwen3-Embedding-0.6B"}


class NotReadyError(Exception):
    pass


def build_embedder(settings: Settings, device: str) -> Embedder:
    if settings.ml_embedder == "fake":
        return FakeEmbedder()
    if settings.ml_embedder == "qwen3":
        return SentenceTransformerEmbedder(
            EMBEDDER_MODELS["qwen3"],
            device=device,
            query_prompt=qwen3_query_prompt(settings.ml_query_task),
            max_tokens=settings.ml_embed_max_tokens,
            batch_size=settings.ml_embed_batch_size,
            padding_side="left",
        )
    raise ValueError(f"неизвестный эмбеддер: {settings.ml_embedder}")


class ModelHub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.status: Literal["loading", "ok", "error"] = "loading"
        self.error: str | None = None
        self.device = resolve_device(settings.ml_device)
        self.embedder: Embedder | None = None
        self.reranker: Reranker | None = None
        self._embed_lock = asyncio.Lock()
        self._rerank_lock = asyncio.Lock()

    def _load_sync(self) -> None:
        started = time.perf_counter()
        embedder = build_embedder(self.settings, self.device)
        embedder.encode(["прогрев"], "query")
        self.embedder = embedder
        log.info(
            "ml.loaded",
            embedder=embedder.name,
            device=self.device,
            seconds=round(time.perf_counter() - started, 1),
        )

    async def load(self) -> None:
        try:
            await asyncio.to_thread(self._load_sync)
            self.status = "ok"
        except Exception as exc:
            log.exception("ml.load_failed")
            self.status, self.error = "error", repr(exc)

    async def embed(self, texts: list[str], kind: Kind) -> list[list[float]]:
        if self.embedder is None:
            raise NotReadyError
        async with self._embed_lock:
            return await asyncio.to_thread(self.embedder.encode, texts, kind)

    def health(self) -> dict[str, Any]:
        def info(model: Embedder | Reranker | None, backend: str) -> dict[str, Any]:
            return {
                "backend": backend,
                "model": model.name if model else None,
                "loaded": model is not None,
                **({"dim": model.dim} if model is not None and hasattr(model, "dim") else {}),
            }

        return {
            "status": self.status,
            "device": self.device,
            "error": self.error,
            "embedder": info(self.embedder, self.settings.ml_embedder),
        }
