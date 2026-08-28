"""Authenticated read-only evidence ledger endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .repository import SqlAlchemyEvidenceRepository
from .schemas import (
    EvidenceEventPage,
    PortfolioHistoryResponse,
    SkillListResponse,
    SkillSummaryResponse,
)
from .service import (
    EvidenceConflict,
    EvidenceInvalidRequest,
    EvidenceNotFound,
    EvidenceQueryService,
)

router = APIRouter(prefix="/api/v1", tags=["evidence"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_evidence_query_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EvidenceQueryService:
    return EvidenceQueryService(SqlAlchemyEvidenceRepository(session))


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    response: Response,
    service: Annotated[EvidenceQueryService, Depends(get_evidence_query_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> SkillListResponse:
    result = await service.list_skills(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.get("/skills/{skill_slug}", response_model=SkillSummaryResponse)
async def get_skill(
    skill_slug: str,
    response: Response,
    service: Annotated[EvidenceQueryService, Depends(get_evidence_query_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> SkillSummaryResponse:
    result = await service.get_skill(owner_id=owner.owner_id, skill_slug=skill_slug)
    _prevent_storage(response)
    return result


@router.get("/skills/{skill_slug}/evidence", response_model=EvidenceEventPage)
async def list_skill_evidence(
    skill_slug: str,
    response: Response,
    service: Annotated[EvidenceQueryService, Depends(get_evidence_query_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    cursor: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EvidenceEventPage:
    result = await service.list_skill_evidence(
        owner_id=owner.owner_id,
        skill_slug=skill_slug,
        cursor=cursor,
        limit=limit,
    )
    _prevent_storage(response)
    return result


@router.get("/activities/{activity_id}/evidence", response_model=EvidenceEventPage)
async def list_activity_evidence(
    activity_id: int,
    response: Response,
    service: Annotated[EvidenceQueryService, Depends(get_evidence_query_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    cursor: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EvidenceEventPage:
    result = await service.list_activity_evidence(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        cursor=cursor,
        limit=limit,
    )
    _prevent_storage(response)
    return result


@router.get("/portfolio-judgment", response_model=PortfolioHistoryResponse)
async def get_portfolio_history(
    response: Response,
    service: Annotated[EvidenceQueryService, Depends(get_evidence_query_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    cursor: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PortfolioHistoryResponse:
    result = await service.portfolio_history(
        owner_id=owner.owner_id,
        cursor=cursor,
        limit=limit,
    )
    _prevent_storage(response)
    return result


def evidence_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, EvidenceNotFound):
        status, code, title = 404, "evidence_not_found", "Evidence not found"
    elif isinstance(exc, EvidenceInvalidRequest):
        status, code, title = 422, "invalid_evidence_request", "Invalid evidence request"
    elif isinstance(exc, EvidenceConflict):
        status, code, title = 409, "evidence_lineage_conflict", "Evidence lineage conflict"
    else:
        status, code, title = 500, "evidence_error", "Evidence operation failed"
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


async def evidence_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return evidence_problem_response(exc)


__all__ = [
    "evidence_exception_handler",
    "get_evidence_query_service",
    "router",
]
