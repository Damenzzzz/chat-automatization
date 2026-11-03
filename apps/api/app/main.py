from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.routers import auth, me, team


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.env == "prod")

    app = FastAPI(title="Satushy API", version="0.1.0")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(team.router)
    return app


app = create_app()
