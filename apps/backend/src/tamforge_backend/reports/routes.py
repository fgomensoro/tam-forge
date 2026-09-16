"""Weekly reports: the list, one week, and a request by hand."""

from __future__ import annotations

from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.weekly_report import WeeklyReportService
from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..config import Settings
from ..database import get_db_session
from .schemas import WeeklyReportPage, WeeklyReportRequestCommand, WeeklyReportResponse
from .service import (
    ReportConflict,
    ReportInvalid,
    ReportNotFound,
    ReportsUnavailable,
    WeeklyReportQueue,
)

router = APIRouter(prefix="/api/v1/reports/weekly", tags=["reports"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_weekly_report_queue(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WeeklyReportQueue:
    settings = cast(Settings, request.app.state.settings)
    transport = getattr(request.app.state, "report_transport", None)
    if not settings.claude_enabled:
        transport = None
    sender = getattr(request.app.state, "report_sender", None)
    return WeeklyReportQueue(
        session,
        analyst=WeeklyReportService(transport, model=settings.report_model),
        sender=sender,
    )


@router.get("", response_model=WeeklyReportPage)
async def list_weekly_reports(
    response: Response,
    service: Annotated[WeeklyReportQueue, Depends(get_weekly_report_queue)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> WeeklyReportPage:
    result = await service.list(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.post("", response_model=WeeklyReportResponse, status_code=202)
async def request_weekly_report(
    command: WeeklyReportRequestCommand,
    response: Response,
    service: Annotated[WeeklyReportQueue, Depends(get_weekly_report_queue)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> WeeklyReportResponse:
    """Ask for a week's report now; the worker composes it."""
    result = await service.request(owner_id=owner.owner_id, week_start=command.week_start)
    _prevent_storage(response)
    return result


@router.get("/{week_start}", response_model=WeeklyReportResponse)
async def read_weekly_report(
    week_start: date,
    response: Response,
    service: Annotated[WeeklyReportQueue, Depends(get_weekly_report_queue)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> WeeklyReportResponse:
    result = await service.read(owner_id=owner.owner_id, week_start=week_start)
    _prevent_storage(response)
    return result


async def reports_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    if isinstance(exc, ReportNotFound):
        status, code, title = 404, "report_not_found", "Report not found"
    elif isinstance(exc, ReportInvalid):
        status, code, title = 422, "report_invalid", "Invalid report request"
    elif isinstance(exc, ReportConflict):
        status, code, title = 409, "report_conflict", "Report already exists"
    elif isinstance(exc, ReportsUnavailable):
        status, code, title = 503, "reports_unavailable", "Reports unavailable"
    else:
        status, code, title = 500, "reports_error", "Report operation failed"
    problem = ProblemResponse(
        type=f"https://tamforge.local/problems/{code}",
        title=title,
        status=status,
        detail=title + ".",
        code=code,
    )
    response = JSONResponse(
        problem.model_dump(), status_code=status, media_type="application/problem+json"
    )
    _prevent_storage(response)
    return response


__all__ = ["get_weekly_report_queue", "reports_exception_handler", "router"]
