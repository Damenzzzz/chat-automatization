import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.hub import ModelHub, NotReadyError
from app.models.base import Kind


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1)
    kind: Kind = "document"


class EmbedOut(BaseModel):
    model: str
    dim: int
    embeddings: list[list[float]]


class RerankIn(BaseModel):
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1)


class RerankOut(BaseModel):
    model: str
    scores: list[float]


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(format="%(message)s", level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
            if settings.env == "prod"
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
    )


def _hub(request: Request) -> ModelHub:
    hub: ModelHub = request.app.state.hub
    return hub


def _not_ready(hub: ModelHub) -> HTTPException:
    detail = "models_failed" if hub.status == "error" else "models_loading"
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        hub = ModelHub(settings)
        app.state.hub = hub
        app.state.loader = asyncio.create_task(hub.load())
        yield

    app = FastAPI(title="Satushy ML", version="0.1.0", lifespan=lifespan)

    @app.get("/health", tags=["system"])
    async def health(request: Request) -> dict[str, Any]:
        return _hub(request).health()

    @app.post("/embed")
    async def embed(body: EmbedIn, request: Request) -> EmbedOut:
        if len(body.texts) > settings.ml_max_texts:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_many_texts")
        if any(len(t) > settings.ml_max_text_chars for t in body.texts):
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "text_too_long")
        hub = _hub(request)
        try:
            vectors = await hub.embed(body.texts, body.kind)
        except NotReadyError as exc:
            raise _not_ready(hub) from exc
        assert hub.embedder is not None  # noqa: S101
        return EmbedOut(model=hub.embedder.name, dim=hub.embedder.dim, embeddings=vectors)

    @app.post("/rerank")
    async def rerank(body: RerankIn, request: Request) -> RerankOut:
        if len(body.documents) > settings.ml_rerank_max_docs:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_many_documents")
        texts = [body.query, *body.documents]
        if any(len(t) > settings.ml_max_text_chars for t in texts):
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "text_too_long")
        hub = _hub(request)
        try:
            scores = await hub.rerank(body.query, body.documents)
        except NotReadyError as exc:
            raise _not_ready(hub) from exc
        assert hub.reranker is not None  # noqa: S101
        return RerankOut(model=hub.reranker.name, scores=scores)

    return app


app = create_app()
