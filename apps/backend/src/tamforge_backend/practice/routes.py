"""Free interview practice endpoints: store a recorded answer, list them with reviews."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.practice_review import PracticeReviewService
from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..config import Settings
from ..database import get_db_session
from .schemas import PracticeAnswerCommand, PracticeAnswerPage, PracticeAnswerResponse
from .service import (
    PracticeAnswerService,
    PracticeInvalid,
    PracticeNotFound,
    PracticeUnavailable,
)

router = APIRouter(prefix="/api/v1/practice-answers", tags=["practice"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_practice_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PracticeAnswerService:
    settings = cast(Settings, request.app.state.settings)
    transport = getattr(request.app.state, "practice_review_transport", None)
    if not settings.claude_enabled:
        transport = None
    return PracticeAnswerService(
        session, reviewer=PracticeReviewService(transport, model=settings.reviewer_model)
    )


@router.post("", response_model=PracticeAnswerResponse, status_code=202)
async def submit_practice_answer(
    command: PracticeAnswerCommand,
    response: Response,
    service: Annotated[PracticeAnswerService, Depends(get_practice_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> PracticeAnswerResponse:
    """Store one recorded practice answer and queue its review once it is transcribed.
    Safe to repeat for the same recording; the worker runs the review."""
    result = await service.submit(owner_id=owner.owner_id, command=command)
    _prevent_storage(response)
    return result


@router.get("", response_model=PracticeAnswerPage)
async def list_practice_answers(
    response: Response,
    service: Annotated[PracticeAnswerService, Depends(get_practice_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> PracticeAnswerPage:
    result = await service.list(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


def practice_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, PracticeNotFound):
        status, code, title = 404, "practice_not_found", "Practice answer or recording not found"
    elif isinstance(exc, PracticeInvalid):
        status, code, title = 422, "practice_invalid", "Invalid practice answer"
    elif isinstance(exc, PracticeUnavailable):
        status, code, title = 503, "practice_unavailable", "Practice unavailable"
    else:
        status, code, title = 500, "practice_error", "Practice operation failed"
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


async def practice_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return practice_problem_response(exc)


__all__ = [
    "get_practice_service",
    "practice_exception_handler",
    "practice_problem_response",
    "router",
]
