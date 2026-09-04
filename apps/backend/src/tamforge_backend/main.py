"""FastAPI application entrypoint and resource lifecycle."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import register_routes
from .config import Settings
from .database import create_database_resources
from .observability.health import HealthRegistry
from .observability.logging import AccessLogFilter, ServerErrorFilter
from .observability.metrics import Metrics
from .observability.middleware import OperationalMiddleware
from .observability.routes import router as operational_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create one app with one immutable settings and database lifecycle."""
    configured = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        access_logger = logging.getLogger("uvicorn.access")
        access_log_filter = AccessLogFilter()
        error_logger = logging.getLogger("uvicorn.error")
        error_log_filter = ServerErrorFilter()
        operations_logger = logging.getLogger("tamforge.operations")
        previous_operations_level = operations_logger.level
        previous_operations_disabled = operations_logger.disabled
        operations_handler = logging.StreamHandler()
        operations_handler.setFormatter(logging.Formatter("%(message)s"))
        operations_logger.addHandler(operations_handler)
        operations_logger.setLevel(logging.INFO)
        operations_logger.disabled = False
        access_logger.addFilter(access_log_filter)
        error_logger.addFilter(error_log_filter)
        database = None
        try:
            database = create_database_resources(configured)
            app.state.settings = configured
            app.state.database = database
            app.state.oauth_state_manager = None
            yield
        finally:
            try:
                if database is not None:
                    await database.dispose()
            finally:
                access_logger.removeFilter(access_log_filter)
                error_logger.removeFilter(error_log_filter)
                operations_logger.removeHandler(operations_handler)
                operations_handler.close()
                operations_logger.setLevel(previous_operations_level)
                operations_logger.disabled = previous_operations_disabled

    app = FastAPI(title="TAM Forge API", version="0.1.0", lifespan=lifespan)
    app.state.operational_health = HealthRegistry()
    app.state.operational_metrics = Metrics()
    app.add_middleware(OperationalMiddleware, metrics=app.state.operational_metrics)
    app.include_router(operational_router)
    if configured.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=configured.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-CSRF-Token",
            ],
        )
    register_routes(app)

    @app.get("/healthz", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "tam-forge-backend"}

    return app


app = create_app()
