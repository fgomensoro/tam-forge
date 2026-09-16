"""One read: everything the Progress screen shows."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .schemas import ProgressResponse
from .service import ProgressQueryService

router = APIRouter(prefix="/api/v1/progress", tags=["progress"])


def get_progress_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProgressQueryService:
    return ProgressQueryService(session)


@router.get("", response_model=ProgressResponse)
async def read_progress(
    response: Response,
    service: Annotated[ProgressQueryService, Depends(get_progress_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ProgressResponse:
    result = await service.read(owner_id=owner.owner_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return result


async def progress_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request, exc
    problem = ProblemResponse(
        type="https://tamforge.local/problems/progress_unavailable",
        title="Progress unavailable",
        status=503,
        detail="Progress unavailable.",
        code="progress_unavailable",
    )
    response = JSONResponse(
        problem.model_dump(), status_code=503, media_type="application/problem+json"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


__all__ = ["get_progress_service", "progress_exception_handler", "router"]
