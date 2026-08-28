"""Authenticated Today read and CSRF-protected daily close routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .repository import SqlAlchemyTodayRepository
from .schemas import DailyCloseCommand, DailyCloseResponse, TodayResponse
from .service import (
    TodayConflict,
    TodayInvalidRequest,
    TodayNotReady,
    TodayService,
)

router = APIRouter(prefix="/api/v1/today", tags=["today"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_today_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TodayService:
    return TodayService(SqlAlchemyTodayRepository(session))


@router.get("", response_model=TodayResponse)
async def get_today(
    response: Response,
    service: Annotated[TodayService, Depends(get_today_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    local_date: Annotated[date, Query(alias="date")],
) -> TodayResponse:
    result = await service.get_today(owner_id=owner.owner_id, local_date=local_date)
    _prevent_storage(response)
    response.headers["ETag"] = result.etag
    return result


@router.post("/{local_date}/close", response_model=DailyCloseResponse)
async def close_today(
    local_date: date,
    command: DailyCloseCommand,
    response: Response,
    service: Annotated[TodayService, Depends(get_today_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        ),
    ],
) -> DailyCloseResponse:
    result = await service.close_day(
        owner_id=owner.owner_id,
        local_date=local_date,
        command=command,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


def today_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, TodayNotReady):
        status, code, title = 404, "today_not_ready", "Today is not ready"
    elif isinstance(exc, TodayConflict):
        status, code, title = 409, "today_conflict", "Today operation conflicts"
    elif isinstance(exc, TodayInvalidRequest):
        status, code, title = 422, "invalid_today_request", "Invalid Today request"
    else:
        status, code, title = 500, "today_error", "Today operation failed"
    problem = ProblemResponse(
        type=f"https://tamforge.local/problems/{code}",
        title=title,
        status=status,
        detail=title + ".",
        code=code,
    )
    response = JSONResponse(
        problem.model_dump(),
        status_code=status,
        media_type="application/problem+json",
    )
    _prevent_storage(response)
    return response


async def today_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return today_problem_response(exc)


__all__ = ["get_today_service", "router", "today_exception_handler"]
