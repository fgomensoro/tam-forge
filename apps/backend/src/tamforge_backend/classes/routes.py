"""English class endpoints: list, create, edit, and attach a recording."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.class_analysis import ClassAnalysisService
from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..config import Settings
from ..database import get_db_session
from .analysis import EnglishClassAnalysisService
from .schemas import (
    AttachClassRecordingCommand,
    ClassAnalysisResponse,
    EnglishClassCommand,
    EnglishClassPage,
    EnglishClassResponse,
)
from .service import (
    ClassConflict,
    ClassesUnavailable,
    ClassInvalid,
    ClassNotFound,
    EnglishClassService,
)

router = APIRouter(prefix="/api/v1/english-classes", tags=["english-classes"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_english_class_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EnglishClassService:
    return EnglishClassService(session)


def get_class_analysis_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EnglishClassAnalysisService:
    settings = cast(Settings, request.app.state.settings)
    transport = getattr(request.app.state, "class_analysis_transport", None)
    if not settings.claude_enabled:
        transport = None
    return EnglishClassAnalysisService(
        session, analyst=ClassAnalysisService(transport, model=settings.reviewer_model)
    )


@router.get("", response_model=EnglishClassPage)
async def list_classes(
    response: Response,
    service: Annotated[EnglishClassService, Depends(get_english_class_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> EnglishClassPage:
    result = await service.list(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.post("", response_model=EnglishClassResponse, status_code=201)
async def create_class(
    command: EnglishClassCommand,
    response: Response,
    service: Annotated[EnglishClassService, Depends(get_english_class_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> EnglishClassResponse:
    result = await service.create(owner_id=owner.owner_id, command=command)
    _prevent_storage(response)
    return result


@router.get("/{class_id}", response_model=EnglishClassResponse)
async def read_class(
    class_id: int,
    response: Response,
    service: Annotated[EnglishClassService, Depends(get_english_class_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> EnglishClassResponse:
    result = await service.get(owner_id=owner.owner_id, class_id=class_id)
    _prevent_storage(response)
    return result


@router.put("/{class_id}", response_model=EnglishClassResponse)
async def update_class(
    class_id: int,
    command: EnglishClassCommand,
    response: Response,
    service: Annotated[EnglishClassService, Depends(get_english_class_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> EnglishClassResponse:
    result = await service.update(owner_id=owner.owner_id, class_id=class_id, command=command)
    _prevent_storage(response)
    return result


@router.post("/{class_id}/recordings", response_model=EnglishClassResponse)
async def attach_class_recording(
    class_id: int,
    command: AttachClassRecordingCommand,
    response: Response,
    service: Annotated[EnglishClassService, Depends(get_english_class_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> EnglishClassResponse:
    result = await service.attach_recording(
        owner_id=owner.owner_id, class_id=class_id, recording_id=command.recording_id
    )
    _prevent_storage(response)
    return result


@router.post("/{class_id}/analysis", response_model=ClassAnalysisResponse, status_code=202)
async def request_class_analysis(
    class_id: int,
    response: Response,
    service: Annotated[EnglishClassAnalysisService, Depends(get_class_analysis_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ClassAnalysisResponse:
    """Queue the analysis of this class's recording; the worker runs it."""
    result = await service.request(owner_id=owner.owner_id, class_id=class_id)
    _prevent_storage(response)
    return result


@router.get("/{class_id}/analysis", response_model=ClassAnalysisResponse)
async def read_class_analysis(
    class_id: int,
    response: Response,
    service: Annotated[EnglishClassAnalysisService, Depends(get_class_analysis_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ClassAnalysisResponse:
    result = await service.read(owner_id=owner.owner_id, class_id=class_id)
    _prevent_storage(response)
    return result


def classes_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, ClassNotFound):
        status, code, title = 404, "class_not_found", "Class not found"
    elif isinstance(exc, ClassInvalid):
        status, code, title = 422, "class_invalid", "Invalid class command"
    elif isinstance(exc, ClassConflict):
        status, code, title = 409, "class_conflict", "Recording belongs to another class"
    elif isinstance(exc, ClassesUnavailable):
        status, code, title = 503, "classes_unavailable", "Classes unavailable"
    else:
        status, code, title = 500, "classes_error", "Class operation failed"
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


async def classes_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return classes_problem_response(exc)


__all__ = ["classes_exception_handler", "get_english_class_service", "router"]
