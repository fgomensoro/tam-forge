"""Authenticated activity state and durable focused-timer HTTP commands."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .schemas import (
    ActivityResponse,
    HeartbeatCommand,
    IncompleteCommand,
    VersionedCommand,
)
from .service import (
    ActivityConflict,
    ActivityInvalidRequest,
    ActivityNotFound,
    ActivityService,
)

router = APIRouter(prefix="/api/v1/activities", tags=["activities"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_activity_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ActivityService:
    return ActivityService(session)


@router.get("/{activity_id}", response_model=ActivityResponse)
async def get_activity(
    activity_id: int,
    response: Response,
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ActivityResponse:
    result = await service.get_activity(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


@router.post("/{activity_id}/start", response_model=ActivityResponse)
async def start_activity(
    activity_id: int,
    command: VersionedCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ActivityResponse:
    result = await service.start(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post("/{activity_id}/pause", response_model=ActivityResponse)
async def pause_activity(
    activity_id: int,
    command: HeartbeatCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ActivityResponse:
    result = await service.pause(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        client_sequence=command.client_sequence,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post("/{activity_id}/resume", response_model=ActivityResponse)
async def resume_activity(
    activity_id: int,
    command: VersionedCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ActivityResponse:
    result = await service.resume(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post("/{activity_id}/heartbeat", response_model=ActivityResponse)
async def heartbeat_activity(
    activity_id: int,
    command: HeartbeatCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ActivityResponse:
    result = await service.heartbeat(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        client_sequence=command.client_sequence,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post("/{activity_id}/classify-incomplete", response_model=ActivityResponse)
async def classify_activity_incomplete(
    activity_id: int,
    command: IncompleteCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ActivityResponse:
    result = await service.classify_incomplete(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        classification=command.classification,
        stronger_evidence_id=command.stronger_evidence_id,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


def activity_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, ActivityNotFound):
        status, code, title = 404, "activity_not_found", "Activity not found"
    elif isinstance(exc, ActivityInvalidRequest):
        status, code, title = 422, "invalid_activity_command", "Invalid activity command"
    elif isinstance(exc, ActivityConflict):
        status, code, title = 409, "activity_state_conflict", "Activity state conflict"
    else:
        status, code, title = 500, "activity_error", "Activity operation failed"
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


async def activity_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return activity_problem_response(exc)
