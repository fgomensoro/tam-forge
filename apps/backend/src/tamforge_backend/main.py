"""FastAPI application entrypoint and resource lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings
from .database import create_database_resources


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create one app with one immutable settings and database lifecycle."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configured = settings if settings is not None else Settings()
        database = create_database_resources(configured)
        app.state.settings = configured
        app.state.database = database
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(title="TAM Forge API", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "tam-forge-backend"}

    return app


app = create_app()
