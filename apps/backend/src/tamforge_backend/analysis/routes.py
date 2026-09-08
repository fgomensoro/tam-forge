"""Authenticated read-only gated feedback endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from tamforge_protocol.agents import FeedbackRead

from ..auth.dependencies import get_authenticated_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .repository import FeedbackNotFound, FeedbackRepository

router = APIRouter(prefix="/api/v1", tags=["analysis"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_feedback_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FeedbackRepository:
    return FeedbackRepository(session)


@router.get(
    "/activities/{activity_id}/attempts/{attempt_id}/feedback", response_model=FeedbackRead
)
async def read_feedback(
    response: Response,
    repository: Annotated[FeedbackRepository, Depends(get_feedback_repository)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    activity_id: Annotated[int, Path(ge=1)],
    attempt_id: Annotated[int, Path(ge=1)],
) -> FeedbackRead:
    result = await repository.feedback(
        owner_id=owner.owner_id, activity_id=activity_id, attempt_id=attempt_id
    )
    _prevent_storage(response)
    return result


def feedback_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, FeedbackNotFound):
        status, code, title = 404, "feedback_not_found", "Feedback not found"
    else:
        status, code, title = 500, "feedback_error", "Feedback read failed"
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


async def feedback_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return feedback_problem_response(exc)


__all__ = ["feedback_exception_handler", "get_feedback_repository", "router"]
