"""Coaching thread endpoints, owner-scoped and cache-free like every other workspace."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.coach import CoachService
from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..config import Settings
from ..database import get_db_session
from .schemas import AcceptEvidenceCommand, CoachMessageCommand, CoachThreadResponse
from .service import (
    CoachingConflict,
    CoachingInvalidRequest,
    CoachingNotFound,
    CoachingUnavailable,
    CoachThreadService,
)

router = APIRouter(prefix="/api/v1/activities", tags=["coaching"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_coach_thread_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CoachThreadService:
    settings = cast(Settings, request.app.state.settings)
    transport = getattr(request.app.state, "coach_transport", None)
    if not settings.claude_enabled:
        transport = None
    return CoachThreadService(session, coach=CoachService(transport, model=settings.coach_model))


@router.get("/{activity_id}/coach", response_model=CoachThreadResponse)
async def read_coach_thread(
    activity_id: int,
    response: Response,
    service: Annotated[CoachThreadService, Depends(get_coach_thread_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> CoachThreadResponse:
    result = await service.thread(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


@router.post("/{activity_id}/coach/messages", response_model=CoachThreadResponse)
async def send_coach_message(
    activity_id: int,
    command: CoachMessageCommand,
    response: Response,
    service: Annotated[CoachThreadService, Depends(get_coach_thread_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> CoachThreadResponse:
    result = await service.send(owner_id=owner.owner_id, activity_id=activity_id, text=command.text)
    _prevent_storage(response)
    return result


@router.post("/{activity_id}/coach/evidence", response_model=CoachThreadResponse)
async def accept_coach_evidence(
    activity_id: int,
    command: AcceptEvidenceCommand,
    response: Response,
    service: Annotated[CoachThreadService, Depends(get_coach_thread_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> CoachThreadResponse:
    result = await service.accept_evidence(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        message_id=command.message_id,
        index=command.index,
    )
    _prevent_storage(response)
    return result


def coaching_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, CoachingNotFound):
        status, code, title = 404, "coaching_not_found", "Coaching thread not found"
    elif isinstance(exc, CoachingInvalidRequest):
        status, code, title = 422, "invalid_coaching_command", "Invalid coaching command"
    elif isinstance(exc, CoachingConflict):
        status, code, title = 409, "coaching_not_allowed", "Coaching not allowed here yet"
    elif isinstance(exc, CoachingUnavailable):
        status, code, title = 503, "coach_unavailable", "Coach unavailable"
    else:
        status, code, title = 500, "coaching_error", "Coaching operation failed"
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


async def coaching_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return coaching_problem_response(exc)


__all__ = ["coaching_exception_handler", "coaching_problem_response", "router"]
