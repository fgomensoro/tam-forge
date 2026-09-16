"""Interview record endpoints: list, create, edit, and attach a recording."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from .schemas import (
    AttachRecordingCommand,
    InterviewCommand,
    InterviewPage,
    InterviewResponse,
    InterviewTranscriptCommand,
    InterviewTranscriptResponse,
    ReferenceImportCommand,
    ReferenceImportResponse,
    ReferenceKind,
    ReferencePage,
)
from .service import (
    InterviewConflict,
    InterviewInvalid,
    InterviewNotFound,
    InterviewService,
    InterviewsUnavailable,
    ReferenceMaterialService,
)

router = APIRouter(prefix="/api/v1/interviews", tags=["interviews"])
reference_router = APIRouter(prefix="/api/v1/reference-material", tags=["interviews"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_interview_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InterviewService:
    return InterviewService(session)


def get_reference_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReferenceMaterialService:
    return ReferenceMaterialService(session)


@router.get("", response_model=InterviewPage)
async def list_interviews(
    response: Response,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> InterviewPage:
    result = await service.list(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.post("", response_model=InterviewResponse, status_code=201)
async def create_interview(
    command: InterviewCommand,
    response: Response,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> InterviewResponse:
    result = await service.create(owner_id=owner.owner_id, command=command)
    _prevent_storage(response)
    return result


@router.get("/{interview_id}", response_model=InterviewResponse)
async def read_interview(
    interview_id: int,
    response: Response,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> InterviewResponse:
    result = await service.get(owner_id=owner.owner_id, interview_id=interview_id)
    _prevent_storage(response)
    return result


@router.put("/{interview_id}", response_model=InterviewResponse)
async def update_interview(
    interview_id: int,
    command: InterviewCommand,
    response: Response,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> InterviewResponse:
    result = await service.update(
        owner_id=owner.owner_id, interview_id=interview_id, command=command
    )
    _prevent_storage(response)
    return result


@router.post("/{interview_id}/recordings", response_model=InterviewResponse)
async def attach_recording(
    interview_id: int,
    command: AttachRecordingCommand,
    response: Response,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> InterviewResponse:
    result = await service.attach_recording(
        owner_id=owner.owner_id, interview_id=interview_id, recording_id=command.recording_id
    )
    _prevent_storage(response)
    return result


@router.post(
    "/{interview_id}/transcript", response_model=InterviewTranscriptResponse, status_code=201
)
async def attach_transcript(
    interview_id: int,
    command: InterviewTranscriptCommand,
    response: Response,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> InterviewTranscriptResponse:
    """A transcript without audio; the analysis is transcript-only and says what it left out."""
    result = await service.attach_transcript(
        owner_id=owner.owner_id, interview_id=interview_id, command=command
    )
    _prevent_storage(response)
    return result


@router.get("/{interview_id}/transcript", response_model=InterviewTranscriptResponse)
async def read_transcript(
    interview_id: int,
    response: Response,
    service: Annotated[InterviewService, Depends(get_interview_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> InterviewTranscriptResponse:
    result = await service.transcript(owner_id=owner.owner_id, interview_id=interview_id)
    _prevent_storage(response)
    return result


@reference_router.post("", response_model=ReferenceImportResponse, status_code=201)
async def import_reference_material(
    command: ReferenceImportCommand,
    response: Response,
    service: Annotated[ReferenceMaterialService, Depends(get_reference_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ReferenceImportResponse:
    """Import the answer bank or the story catalog; readiness labels stay unverified."""
    result = await service.import_markdown(owner_id=owner.owner_id, command=command)
    _prevent_storage(response)
    return result


@reference_router.get("", response_model=ReferencePage)
async def list_reference_material(
    response: Response,
    service: Annotated[ReferenceMaterialService, Depends(get_reference_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    kind: Annotated[ReferenceKind | None, Query()] = None,
) -> ReferencePage:
    result = await service.list(owner_id=owner.owner_id, kind=kind)
    _prevent_storage(response)
    return result


def interviews_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, InterviewNotFound):
        status, code, title = 404, "interview_not_found", "Interview not found"
    elif isinstance(exc, InterviewInvalid):
        status, code, title = 422, "interview_invalid", "Invalid interview command"
    elif isinstance(exc, InterviewConflict):
        status, code, title = 409, "interview_conflict", "Recording belongs to another interview"
    elif isinstance(exc, InterviewsUnavailable):
        status, code, title = 503, "interviews_unavailable", "Interviews unavailable"
    else:
        status, code, title = 500, "interviews_error", "Interview operation failed"
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


async def interviews_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return interviews_problem_response(exc)


__all__ = [
    "get_interview_service",
    "get_reference_service",
    "interviews_exception_handler",
    "reference_router",
    "router",
]
