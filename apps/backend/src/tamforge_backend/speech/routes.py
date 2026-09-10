"""Native-bearer transcript submission, listing, and correction routes.

Shares `recordings/routes.py`'s `/api/v1/recordings` prefix on purpose, not
just for URL consistency: `auth.routes.request_validation_exception_handler`
sanitizes every `RequestValidationError` under that prefix into a generic
`invalid_recording_request` problem instead of FastAPI's default handler,
which echoes the rejected value back in the response. Sharing the prefix is
what keeps a malformed transcript submission from ever echoing transcript
text back in a 422 body.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_bearer_authenticated_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from ..recordings.schemas import IdempotencyKey
from .contracts import (
    TranscriptConflict,
    TranscriptError,
    TranscriptNotFound,
    TranscriptTooLarge,
    TranscriptUnavailable,
)
from .repository import SqlAlchemyTranscriptRepository
from .schemas import (
    Track,
    TranscriptCorrectionCommand,
    TranscriptCorrectionResponse,
    TranscriptPage,
    TranscriptResponse,
    TranscriptSubmitCommand,
)
from .service import TranscriptService

router = APIRouter(prefix="/api/v1/recordings", tags=["speech"])


def _transcript_problem_response_schema(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemResponse"}
            }
        },
    }


TRANSCRIPT_SUBMIT_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _transcript_problem_response_schema("Native bearer authentication is required."),
    404: _transcript_problem_response_schema("Recording was not found."),
    409: _transcript_problem_response_schema("Transcript conflicts with durable state."),
    413: _transcript_problem_response_schema("Transcript body exceeds the size limit."),
    422: _transcript_problem_response_schema("Transcript request validation failed."),
    503: _transcript_problem_response_schema("Transcript storage is temporarily unavailable."),
}
TRANSCRIPT_LIST_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _transcript_problem_response_schema("Native bearer authentication is required."),
    404: _transcript_problem_response_schema("Recording was not found."),
    422: _transcript_problem_response_schema("Transcript request validation failed."),
    503: _transcript_problem_response_schema("Transcript storage is temporarily unavailable."),
}
TRANSCRIPT_CORRECTION_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _transcript_problem_response_schema("Native bearer authentication is required."),
    404: _transcript_problem_response_schema("Recording or transcript track was not found."),
    409: _transcript_problem_response_schema(
        "Transcript already holds the maximum number of corrections."
    ),
    413: _transcript_problem_response_schema("Correction body exceeds the size limit."),
    422: _transcript_problem_response_schema("Correction request validation failed."),
    503: _transcript_problem_response_schema("Transcript storage is temporarily unavailable."),
}


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_transcript_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SqlAlchemyTranscriptRepository:
    return SqlAlchemyTranscriptRepository(session)


def get_transcript_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    repository: Annotated[SqlAlchemyTranscriptRepository, Depends(get_transcript_repository)],
) -> TranscriptService:
    return TranscriptService(session, repository)


@router.post(
    "/{recording_id}/transcripts",
    response_model=TranscriptResponse,
    status_code=201,
    responses=TRANSCRIPT_SUBMIT_RESPONSES,
)
async def submit_transcript(
    recording_id: UUID,
    command: TranscriptSubmitCommand,
    response: Response,
    # Required for wire parity with every other recording write endpoint. Both
    # writes in this domain get their idempotency from a content hash inside the
    # repository instead of from this key: store() dedupes on
    # (owner, recording, track) content equality, so a retried submission
    # replays the stored transcript. The key itself is validated for shape and
    # otherwise unused here.
    idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    owner: Annotated[AuthenticatedOwner, Depends(get_bearer_authenticated_owner)],
    service: Annotated[TranscriptService, Depends(get_transcript_service)],
) -> TranscriptResponse:
    del idempotency_key
    result = await service.submit(
        owner_id=owner.owner_id, recording_id=recording_id, command=command
    )
    _prevent_storage(response)
    return result


@router.get(
    "/{recording_id}/transcripts",
    response_model=TranscriptPage,
    responses=TRANSCRIPT_LIST_RESPONSES,
)
async def list_transcripts(
    recording_id: UUID,
    response: Response,
    owner: Annotated[AuthenticatedOwner, Depends(get_bearer_authenticated_owner)],
    service: Annotated[TranscriptService, Depends(get_transcript_service)],
) -> TranscriptPage:
    result = await service.list_for_recording(owner_id=owner.owner_id, recording_id=recording_id)
    _prevent_storage(response)
    return result


@router.post(
    "/{recording_id}/transcripts/{track}/corrections",
    response_model=TranscriptCorrectionResponse,
    status_code=201,
    responses=TRANSCRIPT_CORRECTION_RESPONSES,
)
async def submit_correction(
    recording_id: UUID,
    track: Track,
    command: TranscriptCorrectionCommand,
    response: Response,
    # Content-hash idempotency as above, on a different identity:
    # append_correction() dedupes on the correction body's own hash, so a
    # retried POST replays the stored correction (`replayed` true, same
    # correction_id) instead of appending a duplicate annotation.
    idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    owner: Annotated[AuthenticatedOwner, Depends(get_bearer_authenticated_owner)],
    service: Annotated[TranscriptService, Depends(get_transcript_service)],
) -> TranscriptCorrectionResponse:
    del idempotency_key
    result = await service.add_correction(
        owner_id=owner.owner_id, recording_id=recording_id, track=track, command=command
    )
    _prevent_storage(response)
    return result


def transcript_problem_response(exc: TranscriptError) -> JSONResponse:
    if isinstance(exc, TranscriptNotFound):
        status, title, detail, code = (
            404,
            "Transcript not found",
            "Transcript resource was not found.",
            "transcript_not_found",
        )
    elif isinstance(exc, TranscriptConflict):
        status, title, detail, code = (
            409,
            "Transcript conflict",
            "Transcript state conflicts with this request.",
            "transcript_conflict",
        )
    elif isinstance(exc, TranscriptTooLarge):
        status, title, detail, code = (
            413,
            "Transcript too large",
            "Transcript body exceeds the size limit.",
            "transcript_too_large",
        )
    elif isinstance(exc, TranscriptUnavailable):
        status, title, detail, code = (
            503,
            "Transcript unavailable",
            "Transcript storage is temporarily unavailable.",
            "transcript_unavailable",
        )
    else:
        status, title, detail, code = (
            500,
            "Transcript failed",
            "Transcript request failed.",
            "transcript_error",
        )
    problem = ProblemResponse(
        type=f"https://tamforge.local/problems/{code}",
        title=title,
        status=status,
        detail=detail,
        code=code,
    )
    response = JSONResponse(
        problem.model_dump(),
        status_code=status,
        media_type="application/problem+json",
    )
    _prevent_storage(response)
    return response


async def transcript_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    if not isinstance(exc, TranscriptError):
        raise exc
    return transcript_problem_response(exc)


__all__ = ["get_transcript_service", "router", "transcript_exception_handler"]
