"""FastAPI application entrypoint and resource lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import register_routes
from .config import Settings
from .database import create_database_resources


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create one app with one immutable settings and database lifecycle."""
    configured = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = create_database_resources(configured)
        app.state.settings = configured
        app.state.database = database
        app.state.oauth_state_manager = None
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(title="TAM Forge API", version="0.1.0", lifespan=lifespan)
    if configured.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=configured.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
        )
    register_routes(app)

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "tam-forge-backend"}

    return app


app = create_app()
