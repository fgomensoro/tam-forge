"""Assessment days as the app and the weekly report read them."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .schemas import AssessmentDayPage
from .service import AssessmentQueryService

router = APIRouter(prefix="/api/v1/assessments", tags=["assessments"])


def get_assessment_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AssessmentQueryService:
    return AssessmentQueryService(session)


@router.get("", response_model=AssessmentDayPage)
async def list_assessment_days(
    response: Response,
    service: Annotated[AssessmentQueryService, Depends(get_assessment_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    limit: Annotated[int, Query(ge=1, le=52)] = 20,
) -> AssessmentDayPage:
    result = await service.list(owner_id=owner.owner_id, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return result


async def assessments_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request, exc
    problem = ProblemResponse(
        type="https://tamforge.local/problems/assessments_unavailable",
        title="Assessments unavailable",
        status=503,
        detail="Assessments unavailable.",
        code="assessments_unavailable",
    )
    response = JSONResponse(
        problem.model_dump(), status_code=503, media_type="application/problem+json"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


__all__ = ["assessments_exception_handler", "get_assessment_service", "router"]
