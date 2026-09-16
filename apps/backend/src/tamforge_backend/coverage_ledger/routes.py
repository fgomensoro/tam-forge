"""The coverage ledger of the active version, or of a named one."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .schemas import CoverageLedgerResponse
from .service import CoverageLedgerService, CoverageNotFound, CoverageUnavailable

router = APIRouter(prefix="/api/v1", tags=["coverage"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_coverage_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CoverageLedgerService:
    return CoverageLedgerService(session)


@router.get("/coverage", response_model=CoverageLedgerResponse)
async def read_active_coverage(
    response: Response,
    service: Annotated[CoverageLedgerService, Depends(get_coverage_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> CoverageLedgerResponse:
    result = await service.read(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.get("/roadmap-versions/{version_id}/coverage", response_model=CoverageLedgerResponse)
async def read_version_coverage(
    version_id: int,
    response: Response,
    service: Annotated[CoverageLedgerService, Depends(get_coverage_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> CoverageLedgerResponse:
    result = await service.read(owner_id=owner.owner_id, version_id=version_id)
    _prevent_storage(response)
    return result


async def coverage_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    if isinstance(exc, CoverageNotFound):
        status, code, title = 404, "coverage_not_found", "Coverage not found"
    elif isinstance(exc, CoverageUnavailable):
        status, code, title = 503, "coverage_unavailable", "Coverage unavailable"
    else:
        status, code, title = 500, "coverage_error", "Coverage read failed"
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


__all__ = ["coverage_exception_handler", "get_coverage_service", "router"]
