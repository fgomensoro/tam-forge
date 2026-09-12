"""Study note endpoints: per-activity draft, edit and approve; owner-wide search and export."""

from __future__ import annotations

from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.coach import CoachService
from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..config import Settings
from ..database import get_db_session
from ..storage.dependencies import get_object_store
from ..storage.ports import ObjectStore
from .schemas import StudyNoteContent, StudyNoteResponse, StudyNoteSearchResponse
from .service import (
    NoteConflict,
    NoteInvalidRequest,
    NoteNotFound,
    NotesUnavailable,
    StudyNoteService,
)

router = APIRouter(prefix="/api/v1", tags=["notes"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_study_note_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
) -> StudyNoteService:
    settings = cast(Settings, request.app.state.settings)
    transport = getattr(request.app.state, "coach_transport", None)
    if not settings.claude_enabled:
        transport = None
    return StudyNoteService(
        session,
        coach=CoachService(transport, model=settings.coach_model),
        object_store=object_store,
    )


@router.get("/activities/{activity_id}/note", response_model=StudyNoteResponse)
async def read_note(
    activity_id: int,
    response: Response,
    service: Annotated[StudyNoteService, Depends(get_study_note_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> StudyNoteResponse:
    result = await service.get(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


@router.post("/activities/{activity_id}/note/draft", response_model=StudyNoteResponse)
async def draft_note(
    activity_id: int,
    response: Response,
    service: Annotated[StudyNoteService, Depends(get_study_note_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> StudyNoteResponse:
    result = await service.draft(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


@router.put("/activities/{activity_id}/note", response_model=StudyNoteResponse)
async def save_note(
    activity_id: int,
    content: StudyNoteContent,
    response: Response,
    service: Annotated[StudyNoteService, Depends(get_study_note_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> StudyNoteResponse:
    result = await service.save(owner_id=owner.owner_id, activity_id=activity_id, content=content)
    _prevent_storage(response)
    return result


@router.post("/activities/{activity_id}/note/approve", response_model=StudyNoteResponse)
async def approve_note(
    activity_id: int,
    response: Response,
    service: Annotated[StudyNoteService, Depends(get_study_note_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> StudyNoteResponse:
    result = await service.approve(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


@router.get("/notes", response_model=StudyNoteSearchResponse)
async def search_notes(
    response: Response,
    service: Annotated[StudyNoteService, Depends(get_study_note_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    query: Annotated[str, Query(max_length=200)] = "",
) -> StudyNoteSearchResponse:
    result = await service.search(owner_id=owner.owner_id, query=query)
    _prevent_storage(response)
    return result


@router.get(
    "/notes/export",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def export_notes(
    service: Annotated[StudyNoteService, Depends(get_study_note_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
    since: Annotated[date | None, Query()] = None,
    until: Annotated[date | None, Query()] = None,
) -> Response:
    payload = await service.export(owner_id=owner.owner_id, since=since, until=until)
    response = Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="tam-forge-study-notes.zip"'},
    )
    _prevent_storage(response)
    return response


def notes_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, NoteNotFound):
        status, code, title = 404, "note_not_found", "Study note not found"
    elif isinstance(exc, NoteInvalidRequest):
        status, code, title = 422, "invalid_note_command", "Invalid study note command"
    elif isinstance(exc, NoteConflict):
        status, code, title = 409, "note_conflict", "Study note cannot change here"
    elif isinstance(exc, NotesUnavailable):
        status, code, title = 503, "notes_unavailable", "Study notes unavailable"
    else:
        status, code, title = 500, "notes_error", "Study note operation failed"
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


async def notes_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return notes_problem_response(exc)


__all__ = ["get_study_note_service", "notes_exception_handler", "router"]
