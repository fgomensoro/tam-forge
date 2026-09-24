"""Operational endpoints; detailed signals require the existing owner identity."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.token_slots import TokenSlot, choose_slot, read_active_slot
from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner
from ..database import DatabaseResources, get_db_session
from .health import HealthRegistry, probe_dependency
from .metrics import Metrics

router = APIRouter(include_in_schema=False)
NO_STORE = {"Cache-Control": "no-store"}


async def get_database_ready(request: Request) -> bool:
    async def check() -> None:
        database = cast(DatabaseResources, request.app.state.database)
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    return await probe_dependency(check)


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


class TokenSlotChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: TokenSlot


@router.get("/ops/claude/slot")
async def claude_token_slot(
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Which installed subscription token the Claude worker uses; never the token itself."""
    slot = await read_active_slot(session, owner_id=owner.owner_id)
    return JSONResponse({"slot": slot}, headers=NO_STORE)


@router.put("/ops/claude/slot")
async def choose_claude_token_slot(
    choice: TokenSlotChoice,
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """Switch slots; the Claude worker picks the choice up on its next beat."""
    await choose_slot(session, owner_id=owner.owner_id, slot=choice.slot)
    return JSONResponse({"slot": choice.slot}, headers=NO_STORE)
