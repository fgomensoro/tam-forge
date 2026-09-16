"""Card endpoints: create, list, the cards due on a date, grade one, export everything."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .schemas import (
    CardCommand,
    CardPage,
    CardResponse,
    CardReviewResult,
    CardsExport,
    DueCardsResponse,
    ReviewCardCommand,
)
from .service import CardInvalid, CardNotFound, CardService, CardsUnavailable

router = APIRouter(prefix="/api/v1/cards", tags=["cards"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_card_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> CardService:
    return CardService(session)


@router.get("", response_model=CardPage)
async def list_cards(
    response: Response,
    service: Annotated[CardService, Depends(get_card_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> CardPage:
    result = await service.list(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.post("", response_model=CardResponse, status_code=201)
async def create_card(
    command: CardCommand,
    response: Response,
    service: Annotated[CardService, Depends(get_card_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> CardResponse:
    result = await service.create(owner_id=owner.owner_id, command=command)
    _prevent_storage(response)
    return result


@router.get("/due", response_model=DueCardsResponse)
async def due_cards(
    response: Response,
    service: Annotated[CardService, Depends(get_card_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    local_date: Annotated[date, Query(alias="date")],
) -> DueCardsResponse:
    result = await service.due(owner_id=owner.owner_id, local_date=local_date)
    _prevent_storage(response)
    return result


@router.get("/export", response_model=CardsExport)
async def export_cards(
    response: Response,
    service: Annotated[CardService, Depends(get_card_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> CardsExport:
    result = await service.export(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.post("/{card_id}/reviews", response_model=CardReviewResult, status_code=201)
async def review_card(
    card_id: int,
    command: ReviewCardCommand,
    response: Response,
    service: Annotated[CardService, Depends(get_card_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> CardReviewResult:
    result = await service.review(
        owner_id=owner.owner_id,
        card_id=card_id,
        grade=command.grade,
        reviewed_on=command.reviewed_on,
        mode=command.mode,
        recording_id=command.recording_id,
    )
    _prevent_storage(response)
    return result


def cards_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, CardNotFound):
        status, code, title = 404, "card_not_found", "Card not found"
    elif isinstance(exc, CardInvalid):
        status, code, title = 422, "invalid_card_command", "Invalid card command"
    elif isinstance(exc, CardsUnavailable):
        status, code, title = 503, "cards_unavailable", "Cards unavailable"
    else:
        status, code, title = 500, "cards_error", "Card operation failed"
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


async def cards_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return cards_problem_response(exc)


__all__ = ["cards_exception_handler", "get_card_service", "router"]
