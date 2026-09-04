"""Operational endpoints; detailed signals require the existing owner identity."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from ..auth.dependencies import get_authenticated_owner
from ..database import DatabaseResources
from .health import HealthRegistry, probe_database
from .metrics import Metrics

router = APIRouter(include_in_schema=False)
NO_STORE = {"Cache-Control": "no-store"}


async def get_database_ready(request: Request) -> bool:
    async def check() -> None:
        database = cast(DatabaseResources, request.app.state.database)
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    return await probe_database(check)


@router.get("/readyz")
async def readiness(
    request: Request,
    database_ready: Annotated[bool, Depends(get_database_ready)],
) -> JSONResponse:
    health = cast(HealthRegistry, request.app.state.operational_health)
    snapshot = health.snapshot(database_ready=database_ready)
    return JSONResponse(
        {"status": snapshot["status"]},
        status_code=200 if snapshot["ready"] else 503,
        headers=NO_STORE,
    )


@router.get("/ops/status", dependencies=[Depends(get_authenticated_owner)])
async def status(
    request: Request,
    database_ready: Annotated[bool, Depends(get_database_ready)],
) -> JSONResponse:
    health = cast(HealthRegistry, request.app.state.operational_health)
    return JSONResponse(health.snapshot(database_ready=database_ready), headers=NO_STORE)


@router.get("/ops/metrics", dependencies=[Depends(get_authenticated_owner)])
async def metrics(request: Request) -> PlainTextResponse:
    registry = cast(Metrics, request.app.state.operational_metrics)
    return PlainTextResponse(
        registry.render(),
        media_type="text/plain; version=0.0.4",
        headers=NO_STORE,
    )
