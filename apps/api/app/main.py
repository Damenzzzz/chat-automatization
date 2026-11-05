from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.crypto import CryptoError
from app.core.logging import configure_logging
from app.routers import (
    admin,
    auth,
    billing,
    bot_profile,
    catalog,
    channels,
    debug,
    ingest_jobs,
    me,
    sandbox,
    team,
    webhooks,
    widget,
)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.env == "prod")

    app = FastAPI(title="Satushy API", version="0.1.0")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(CryptoError)
    async def crypto_error(request: Request, exc: CryptoError) -> JSONResponse:
        return JSONResponse(
            {"detail": "encryption_not_configured"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(team.router)
    app.include_router(admin.router)
    app.include_router(catalog.router)
    app.include_router(ingest_jobs.router)
    app.include_router(debug.router)
    app.include_router(sandbox.router)
    app.include_router(bot_profile.router)
    app.include_router(billing.router)
    app.include_router(channels.router)
    app.include_router(webhooks.router)
    app.include_router(widget.router)
    return app


app = create_app()
