"""FastAPI application entrypoint and resource lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents.sdk_runtime import AgentSdkRuntime
from .api import register_routes
from .config import Settings
from .database import create_database_resources
from .models.base import utc_now
from .observability.health import (
    HEARTBEAT_INTERVAL_SECONDS,
    HealthRegistry,
    run_health_heartbeat,
    run_probe_loop,
)
from .observability.heartbeats import WorkerHeartbeatStore, report_worker_heartbeats
from .observability.logging import AccessLogFilter, ServerErrorFilter
from .observability.metrics import Metrics
from .observability.middleware import OperationalMiddleware
from .observability.routes import router as operational_router
from .storage.dependencies import create_object_store
from .storage.models import build_object_key
from .storage.ports import ObjectStore

# Ingest depends on the object store, so that is what its heartbeat probes. The key
# names no owner and no artifact, and stat on a key that was never written is a plain
# reachability question with no side effect.
INGEST_PROBE_KEY = build_object_key(
    artifact_class="health", owner_id="probe", logical_id="readiness", sha256="0" * 64
)


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
        heartbeat = None
        worker_reader = None
        try:
            database = create_database_resources(configured)
            app.state.settings = configured
            app.state.database = database
            app.state.oauth_state_manager = None
            # The planner's seam to Claude. PlannerService still refuses while Claude
            # is disabled; constructing the runtime reads no credential.
            app.state.planner_transport = AgentSdkRuntime()

            async def probe_ingest() -> None:
                # Built here rather than at startup on purpose. The store is
                # constructed lazily on first use, so an application configured
                # without object-store credentials still starts and still serves
                # every path that does not touch it. A construction failure is a
                # probe failure, which reports ingest as needing attention instead
                # of taking the whole application down.
                store: ObjectStore | None = getattr(app.state, "object_store", None)
                if store is None:
                    store = create_object_store(configured)
                    app.state.object_store = store
                await store.stat(INGEST_PROBE_KEY)

            heartbeat = asyncio.create_task(
                run_health_heartbeat(
                    app.state.operational_health, component="ingest", probe=probe_ingest
                )
            )
            app.state.ingest_heartbeat = heartbeat
            heartbeat_store = WorkerHeartbeatStore(database.session_factory)

            async def read_worker_heartbeats() -> None:
                await report_worker_heartbeats(
                    app.state.operational_health, heartbeat_store, now=utc_now()
                )

            worker_reader = asyncio.create_task(
                run_probe_loop(read_worker_heartbeats, interval_seconds=HEARTBEAT_INTERVAL_SECONDS)
            )
            app.state.worker_heartbeat_reader = worker_reader
            yield
        finally:
            if worker_reader is not None:
                worker_reader.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await worker_reader
            if heartbeat is not None:
                heartbeat.cancel()
                # A heartbeat that already died carries its own exception, and awaiting
                # it re-raises that from inside this finally block, masking whatever we
                # are actually shutting down for. KeyboardInterrupt and SystemExit still
                # propagate.
                with suppress(asyncio.CancelledError, Exception):
                    await heartbeat
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
