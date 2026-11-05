import asyncio
import time
from pathlib import Path
from typing import Any, Literal

import structlog

from app.config import Settings
from app.models.asr import Transcriber, Transcript, WhisperTranscriber
from app.models.base import Embedder, Kind, Reranker, resolve_device, resolve_dtype
from app.models.embedders import SentenceTransformerEmbedder, qwen3_query_prompt
from app.models.fake import FakeEmbedder, FakeReranker, FakeTranscriber
from app.models.rerankers import CrossEncoderReranker, Qwen3Reranker

log = structlog.get_logger()

EMBEDDER_MODELS = {"qwen3": "Qwen/Qwen3-Embedding-0.6B", "bge-m3": "BAAI/bge-m3"}
RERANKER_MODELS = {"qwen3": "Qwen/Qwen3-Reranker-0.6B", "bge-m3": "BAAI/bge-reranker-v2-m3"}


class NotReadyError(Exception):
    pass


def build_embedder(settings: Settings, device: str) -> Embedder:
    if settings.ml_embedder == "fake":
        return FakeEmbedder()
    if settings.ml_embedder == "qwen3":
        return SentenceTransformerEmbedder(
            EMBEDDER_MODELS["qwen3"],
            device=device,
            dtype=resolve_dtype(settings.ml_dtype, device),
            query_prompt=qwen3_query_prompt(settings.ml_query_task),
            max_tokens=settings.ml_embed_max_tokens,
            batch_size=settings.ml_embed_batch_size,
            padding_side="left",
        )
    if settings.ml_embedder == "bge-m3":
        return SentenceTransformerEmbedder(
            EMBEDDER_MODELS["bge-m3"],
            device=device,
            dtype=resolve_dtype(settings.ml_dtype, device),
            query_prompt=None,
            max_tokens=settings.ml_embed_max_tokens,
            batch_size=settings.ml_embed_batch_size,
        )
    raise ValueError(f"неизвестный эмбеддер: {settings.ml_embedder}")


def build_reranker(settings: Settings, device: str) -> Reranker:
    if settings.ml_reranker == "fake":
        return FakeReranker()
    if settings.ml_reranker == "qwen3":
        return Qwen3Reranker(
            RERANKER_MODELS["qwen3"],
            device=device,
            dtype=resolve_dtype(settings.ml_dtype, device),
            instruction=settings.ml_query_task,
            max_tokens=settings.ml_rerank_max_tokens,
            batch_size=settings.ml_rerank_batch_size,
        )
    if settings.ml_reranker == "bge-m3":
        return CrossEncoderReranker(
            RERANKER_MODELS["bge-m3"],
            device=device,
            dtype=resolve_dtype(settings.ml_dtype, device),
            max_tokens=min(settings.ml_rerank_max_tokens, 512),
            batch_size=settings.ml_rerank_batch_size,
        )
    raise ValueError(f"неизвестный реранкер: {settings.ml_reranker}")


def build_transcriber(settings: Settings, device: str) -> Transcriber:
    if settings.ml_asr == "fake":
        return FakeTranscriber()
    compute_type = settings.ml_asr_compute_type
    if compute_type == "auto":
        compute_type = "int8" if device == "cpu" else "float16"
    return WhisperTranscriber(
        settings.asr_model,
        settings.kk_asr_model,
        device=device,
        compute_type=compute_type,
        ct2_dir=Path(settings.ml_asr_dir),
        max_seconds=settings.ml_max_audio_seconds,
    )


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
        self.asr: Transcriber | None = None
        self.asr_error: str | None = None
        self._asr_lock = asyncio.Lock()

    def _load_sync(self) -> None:
        started = time.perf_counter()
        embedder = build_embedder(self.settings, self.device)
        embedder.encode(["прогрев"], "query")
        reranker = build_reranker(self.settings, self.device)
        reranker.score("прогрев", ["прогрев"])
        self.embedder, self.reranker = embedder, reranker
        log.info(
            "ml.loaded",
            embedder=embedder.name,
            reranker=reranker.name,
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
        await self.load_asr()

    async def load_asr(self) -> None:
        try:
            self.asr = await asyncio.to_thread(build_transcriber, self.settings, self.device)
            log.info("ml.asr_loaded", model=self.asr.name)
        except Exception as exc:
            log.exception("ml.asr_load_failed")
            self.asr_error = repr(exc)

    async def embed(self, texts: list[str], kind: Kind) -> list[list[float]]:
        if self.embedder is None:
            raise NotReadyError
        async with self._embed_lock:
            return await asyncio.to_thread(self.embedder.encode, texts, kind)

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if self.reranker is None:
            raise NotReadyError
        async with self._rerank_lock:
            return await asyncio.to_thread(self.reranker.score, query, documents)

    async def transcribe(self, audio: bytes) -> Transcript:
        if self.asr is None:
            raise NotReadyError
        async with self._asr_lock:
            return await asyncio.to_thread(self.asr.transcribe, audio)

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
            "reranker": info(self.reranker, self.settings.ml_reranker),
            "asr": {
                "backend": self.settings.ml_asr,
                "model": self.asr.name if self.asr else None,
                "loaded": self.asr is not None,
                "error": self.asr_error,
            },
        }
