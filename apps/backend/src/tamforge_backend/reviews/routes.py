"""Review endpoints: read the AI review of an activity, or ask for one now."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.reviewer import ReviewerService
from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..config import Settings
from ..database import get_db_session
from .schemas import ActivityReviewResponse
from .service import (
    ReviewConflict,
    ReviewInvalid,
    ReviewNotFound,
    ReviewService,
    ReviewsUnavailable,
)

router = APIRouter(prefix="/api/v1/activities", tags=["reviews"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_review_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReviewService:
    settings = cast(Settings, request.app.state.settings)
    # The API only queues and reads; the Claude worker is the one that calls the reviewer.
    return ReviewService(session, reviewer=ReviewerService(None, model=settings.reviewer_model))


@router.get("/{activity_id}/review", response_model=ActivityReviewResponse)
async def read_review(
    activity_id: int,
    response: Response,
    service: Annotated[ReviewService, Depends(get_review_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ActivityReviewResponse:
    result = await service.read(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


@router.post("/{activity_id}/review", response_model=ActivityReviewResponse)
async def request_review(
    activity_id: int,
    response: Response,
    service: Annotated[ReviewService, Depends(get_review_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ActivityReviewResponse:
    result = await service.request(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


def reviews_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, ReviewNotFound):
        status, code, title = 404, "review_not_found", "Review not found"
    elif isinstance(exc, ReviewInvalid):
        status, code, title = 422, "review_invalid", "Attempt cannot be reviewed"
    elif isinstance(exc, ReviewConflict):
        status, code, title = 409, "review_conflict", "Review cannot be requested here"
    elif isinstance(exc, ReviewsUnavailable):
        status, code, title = 503, "reviews_unavailable", "Reviews unavailable"
    else:
        status, code, title = 500, "reviews_error", "Review operation failed"
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


async def reviews_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return reviews_problem_response(exc)


__all__ = ["get_review_service", "reviews_exception_handler", "router"]
