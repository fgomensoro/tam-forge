"""Authenticated notification reads, idempotent read receipts, and SSE."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_auth_service, get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..auth.service import AuthService
from ..database import get_db_session
from .repository import SqlAlchemyNotificationRepository
from .schemas import NotificationPage, NotificationResponse
from .service import (
    NotificationInvalidRequest,
    NotificationNotFound,
    NotificationService,
)
from .sse import parse_last_event_id, status_event_stream

router = APIRouter(prefix="/api/v1", tags=["notifications"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_notification_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationService:
    return NotificationService(SqlAlchemyNotificationRepository(session))


@router.get("/notifications", response_model=NotificationPage)
async def list_notifications(
    response: Response,
    service: Annotated[NotificationService, Depends(get_notification_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    cursor: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NotificationPage:
    result = await service.list_notifications(
        owner_id=owner.owner_id,
        cursor=cursor,
        limit=limit,
    )
    _prevent_storage(response)
    return result


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: int,
    response: Response,
    service: Annotated[NotificationService, Depends(get_notification_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> NotificationResponse:
    result = await service.mark_read(
        owner_id=owner.owner_id,
        notification_id=notification_id,
    )
    _prevent_storage(response)
    return result


@router.get("/events")
async def stream_status_events(
    request: Request,
    service: Annotated[NotificationService, Depends(get_notification_service)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    try:
        cursor = parse_last_event_id(last_event_id)
    except ValueError as exc:
        raise NotificationInvalidRequest("Last-Event-ID is invalid") from exc

    async def session_is_active() -> bool:
        return await auth_service.is_session_active(owner)

    response = StreamingResponse(
        status_event_stream(
            request=request,
            service=service,
            owner_id=owner.owner_id,
            after_event_id=cursor,
            session_is_active=session_is_active,
            monotonic=time.monotonic,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
            "X-Accel-Buffering": "no",
        },
    )
    return response


def notification_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, NotificationNotFound):
        status, code, title = 404, "notification_not_found", "Notification not found"
    elif isinstance(exc, NotificationInvalidRequest):
        status, code, title = 422, "invalid_notification_request", "Invalid notification request"
    else:
        status, code, title = 500, "notification_error", "Notification operation failed"
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


async def notification_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    del request
    return notification_problem_response(exc)


__all__ = [
    "get_notification_service",
    "notification_exception_handler",
    "router",
]
