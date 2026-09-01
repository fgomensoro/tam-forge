"""Native-bearer recording ingest and recovery routes."""

from __future__ import annotations

import base64
import hmac
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_bearer_authenticated_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from ..storage.dependencies import get_object_store
from ..storage.models import ObjectStoreError
from ..storage.ports import ObjectStore
from .repository import SqlAlchemyRecordingRepository
from .schemas import (
    IdempotencyKey,
    PendingRecordingPage,
    RecordingCreateCommand,
    RecordingCreateResponse,
    RecordingPartReceipt,
    RecordingPartUploadMetadata,
    RecordingSealCommand,
    RecordingSealResponse,
    RecordingStatusResponse,
    Sha256,
    TrackKind,
)
from .service import (
    RecordingConflict,
    RecordingError,
    RecordingInvalidRequest,
    RecordingNotFound,
    RecordingService,
    RecordingUnavailable,
)

router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])


def _recording_problem_response_schema(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemResponse"}
            }
        },
    }


RECORDING_CREATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _recording_problem_response_schema("Native bearer authentication is required."),
    409: _recording_problem_response_schema(
        "Recording identity conflicts with an existing request."
    ),
    422: _recording_problem_response_schema("Recording request validation failed."),
    503: _recording_problem_response_schema("Recording service is temporarily unavailable."),
}
RECORDING_PART_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: _recording_problem_response_schema("Recording part metadata is invalid."),
    401: _recording_problem_response_schema("Native bearer authentication is required."),
    404: _recording_problem_response_schema("Recording or track was not found."),
    409: _recording_problem_response_schema("Recording part conflicts with durable state."),
    422: _recording_problem_response_schema("Recording part request validation failed."),
    503: _recording_problem_response_schema("Recording storage is temporarily unavailable."),
}
RECORDING_SEAL_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _recording_problem_response_schema("Native bearer authentication is required."),
    404: _recording_problem_response_schema("Recording was not found."),
    409: _recording_problem_response_schema("Recording seal conflicts with durable state."),
    422: _recording_problem_response_schema("Recording seal request validation failed."),
    503: _recording_problem_response_schema("Recording storage is temporarily unavailable."),
}
RECORDING_PENDING_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _recording_problem_response_schema("Native bearer authentication is required."),
    409: _recording_problem_response_schema("Recording aggregate is incomplete."),
    422: _recording_problem_response_schema("Recording request validation failed."),
    503: _recording_problem_response_schema("Recording service is temporarily unavailable."),
}
RECORDING_STATUS_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: _recording_problem_response_schema("Native bearer authentication is required."),
    404: _recording_problem_response_schema("Recording was not found."),
    409: _recording_problem_response_schema("Recording aggregate is incomplete."),
    422: _recording_problem_response_schema("Recording request validation failed."),
    503: _recording_problem_response_schema("Recording service is temporarily unavailable."),
}


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_recording_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SqlAlchemyRecordingRepository:
    return SqlAlchemyRecordingRepository(session)


def get_recording_object_store(request: Request) -> ObjectStore:
    try:
        return get_object_store(request)
    except (ObjectStoreError, ValueError) as exc:
        raise RecordingUnavailable("recording storage is unavailable") from exc


def get_recording_service(
    repository: Annotated[SqlAlchemyRecordingRepository, Depends(get_recording_repository)],
    object_store: Annotated[ObjectStore, Depends(get_recording_object_store)],
) -> RecordingService:
    return RecordingService(repository, object_store)


@router.post(
    "",
    response_model=RecordingCreateResponse,
    status_code=201,
    responses=RECORDING_CREATE_RESPONSES,
)
async def create_recording(
    command: RecordingCreateCommand,
    response: Response,
    idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    owner: Annotated[AuthenticatedOwner, Depends(get_bearer_authenticated_owner)],
    service: Annotated[RecordingService, Depends(get_recording_service)],
) -> RecordingCreateResponse:
    result = await service.create(
        owner_id=owner.owner_id,
        command=command,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.get(
    "/pending",
    response_model=PendingRecordingPage,
    responses=RECORDING_PENDING_RESPONSES,
)
async def pending_recordings(
    response: Response,
    owner: Annotated[AuthenticatedOwner, Depends(get_bearer_authenticated_owner)],
    service: Annotated[RecordingService, Depends(get_recording_service)],
) -> PendingRecordingPage:
    result = PendingRecordingPage(items=await service.pending(owner_id=owner.owner_id))
    _prevent_storage(response)
    return result


@router.put(
    "/{recording_id}/tracks/{track_id}/parts/{sequence}",
    response_model=RecordingPartReceipt,
    status_code=201,
    responses=RECORDING_PART_RESPONSES,
)
async def upload_recording_part(
    request: Request,
    response: Response,
    recording_id: UUID,
    track_id: UUID,
    sequence: Annotated[int, Path(ge=0, le=7199)],
    idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    schema_version: Annotated[Literal[1], Header(alias="X-TAM-Recording-Schema")],
    track_kind: Annotated[TrackKind, Header(alias="X-TAM-Track-Kind")],
    sample_encoding: Annotated[Literal["pcm_s16le"], Header(alias="X-TAM-Sample-Encoding")],
    sample_rate_hz: Annotated[Literal[48_000], Header(alias="X-TAM-Sample-Rate")],
    channel_count: Annotated[Literal[1, 2], Header(alias="X-TAM-Channel-Count")],
    header_sequence: Annotated[int, Header(alias="X-TAM-Part-Sequence")],
    sample_start: Annotated[int, Header(alias="X-TAM-Sample-Start")],
    sample_count: Annotated[int, Header(alias="X-TAM-Sample-Count")],
    plaintext_length: Annotated[int, Header(alias="X-TAM-Plaintext-Length")],
    ciphertext_length: Annotated[int, Header(alias="X-TAM-Ciphertext-Length")],
    plaintext_sha256: Annotated[Sha256, Header(alias="X-TAM-Plaintext-SHA256")],
    ciphertext_sha256: Annotated[Sha256, Header(alias="X-TAM-Ciphertext-SHA256")],
    nonce_base64url: Annotated[
        str,
        Header(
            alias="X-TAM-Part-Nonce",
            min_length=16,
            max_length=16,
            pattern=r"^[A-Za-z0-9_-]+$",
        ),
    ],
    part_key_base64url: Annotated[
        str,
        Header(
            alias="X-TAM-Part-Key",
            min_length=43,
            max_length=43,
            pattern=r"^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$",
        ),
    ],
    encryption_version: Annotated[
        Literal["aes-256-gcm-hkdf-sha256-v1"],
        Header(alias="X-TAM-Part-Encryption"),
    ],
    owner: Annotated[AuthenticatedOwner, Depends(get_bearer_authenticated_owner)],
    service: Annotated[RecordingService, Depends(get_recording_service)],
) -> RecordingPartReceipt:
    try:
        part_key = base64.b64decode(
            part_key_base64url + "=" * (-len(part_key_base64url) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (TypeError, ValueError):
        raise RecordingInvalidRequest("recording encryption material is invalid") from None
    if len(part_key) != 32:
        raise RecordingInvalidRequest("recording encryption material is invalid")
    canonical_part_key = base64.urlsafe_b64encode(part_key).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(canonical_part_key, part_key_base64url):
        raise RecordingInvalidRequest("recording encryption material is invalid")
    try:
        metadata = RecordingPartUploadMetadata.model_validate(
            {
                "schema_version": schema_version,
                "recording_id": recording_id,
                "track_id": track_id,
                "track_kind": track_kind,
                "format": {
                    "sample_encoding": sample_encoding,
                    "sample_rate_hz": sample_rate_hz,
                    "channel_count": channel_count,
                    "interleaved": True,
                },
                "sequence": header_sequence,
                "sample_start": sample_start,
                "sample_count": sample_count,
                "byte_length": plaintext_length,
                "ciphertext_byte_length": ciphertext_length,
                "plaintext_sha256": plaintext_sha256,
                "ciphertext_sha256": ciphertext_sha256,
                "nonce_base64url": nonce_base64url,
                "encryption_version": encryption_version,
            }
        )
    except ValidationError:
        raise RecordingInvalidRequest("recording part metadata is invalid") from None
    if metadata.sequence != sequence:
        raise RecordingConflict("recording part path and header sequence differ")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > metadata.ciphertext_byte_length:
            raise RecordingConflict("recording part body exceeds declared length")
        body.extend(chunk)
    if len(body) != metadata.ciphertext_byte_length:
        raise RecordingConflict("recording part body length does not match")
    result = await service.upload_part(
        owner_id=owner.owner_id,
        metadata=metadata,
        part_key=part_key,
        ciphertext=bytes(body),
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post(
    "/{recording_id}/seal",
    response_model=RecordingSealResponse,
    status_code=201,
    responses=RECORDING_SEAL_RESPONSES,
)
async def seal_recording(
    recording_id: UUID,
    command: RecordingSealCommand,
    response: Response,
    idempotency_key: Annotated[IdempotencyKey, Header(alias="Idempotency-Key")],
    owner: Annotated[AuthenticatedOwner, Depends(get_bearer_authenticated_owner)],
    service: Annotated[RecordingService, Depends(get_recording_service)],
) -> RecordingSealResponse:
    if command.recording_id != recording_id:
        raise RecordingConflict("recording seal path and manifest differ")
    result = await service.seal(
        owner_id=owner.owner_id,
        command=command,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.get(
    "/{recording_id}",
    response_model=RecordingStatusResponse,
    responses=RECORDING_STATUS_RESPONSES,
)
async def recording_status(
    recording_id: UUID,
    response: Response,
    owner: Annotated[AuthenticatedOwner, Depends(get_bearer_authenticated_owner)],
    service: Annotated[RecordingService, Depends(get_recording_service)],
) -> RecordingStatusResponse:
    result = await service.status(owner_id=owner.owner_id, recording_id=recording_id)
    _prevent_storage(response)
    return result


def recording_problem_response(exc: RecordingError) -> JSONResponse:
    if isinstance(exc, RecordingInvalidRequest):
        status, title, detail, code = (
            400,
            "Invalid recording request",
            "Recording request is invalid.",
            "recording_invalid",
        )
    elif isinstance(exc, RecordingNotFound):
        status, title, detail, code = (
            404,
            "Recording not found",
            "Recording was not found.",
            "recording_not_found",
        )
    elif isinstance(exc, RecordingConflict):
        status, title, detail, code = (
            409,
            "Recording conflict",
            "Recording state conflicts with this request.",
            "recording_conflict",
        )
    elif isinstance(exc, RecordingUnavailable):
        status, title, detail, code = (
            503,
            "Recording unavailable",
            "Recording storage is temporarily unavailable.",
            "recording_unavailable",
        )
    else:
        status, title, detail, code = (
            500,
            "Recording failed",
            "Recording request failed.",
            "recording_error",
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


async def recording_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    if not isinstance(exc, RecordingError):
        raise exc
    return recording_problem_response(exc)


__all__ = ["get_recording_service", "recording_exception_handler", "router"]
