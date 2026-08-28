"""Authenticated activity state and durable focused-timer HTTP commands."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from ..storage.dependencies import get_object_store
from ..storage.models import ObjectStoreError
from ..storage.ports import ObjectStore
from .schemas import (
    ActivityDetailResponse,
    ActivityResponse,
    ArtifactConfirmCommand,
    ArtifactPresignCommand,
    ArtifactPresignResponse,
    ArtifactResponse,
    CommitOutputCommand,
    HeartbeatCommand,
    IncompleteCommand,
    OutputCommitResponse,
    SelfReviewCommand,
    SelfReviewResponse,
    SourceVisibilityCommand,
    VersionedCommand,
)
from .service import (
    ActivityConflict,
    ActivityInvalidRequest,
    ActivityNotFound,
    ActivityService,
    ActivityUnavailable,
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


def get_activity_storage_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ActivityService:
    try:
        object_store: ObjectStore = get_object_store(request)
    except (ValueError, ObjectStoreError) as exc:
        raise ActivityUnavailable("private object storage is unavailable") from exc
    return ActivityService(session, object_store=object_store)


@router.get("/{activity_id}", response_model=ActivityDetailResponse)
async def get_activity(
    activity_id: int,
    response: Response,
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ActivityDetailResponse:
    result = await service.get_activity(owner_id=owner.owner_id, activity_id=activity_id)
    _prevent_storage(response)
    return result


@router.post(
    "/{activity_id}/artifacts/presign",
    response_model=ArtifactPresignResponse,
)
async def presign_activity_artifact(
    activity_id: int,
    command: ArtifactPresignCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_storage_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ArtifactPresignResponse:
    result = await service.presign_artifact(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        artifact_class=command.artifact_class,
        sha256=command.sha256,
        byte_length=command.byte_length,
        content_type=command.content_type,
        original_filename=command.original_filename,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post(
    "/{activity_id}/artifacts/confirm",
    response_model=ArtifactResponse,
)
async def confirm_activity_artifact(
    activity_id: int,
    command: ArtifactConfirmCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_storage_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ArtifactResponse:
    result = await service.confirm_artifact(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        upload_idempotency_key=command.upload_idempotency_key,
        object_key=command.object_key,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post(
    "/{activity_id}/source-visibility",
    response_model=ActivityDetailResponse,
)
async def set_activity_source_visibility(
    activity_id: int,
    command: SourceVisibilityCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ActivityDetailResponse:
    result = await service.set_source_visibility(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        hidden=command.hidden,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post(
    "/{activity_id}/commit-output",
    response_model=OutputCommitResponse,
)
async def commit_activity_output(
    activity_id: int,
    command: CommitOutputCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> OutputCommitResponse:
    result = await service.commit_output(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        client_sequence=command.client_sequence,
        output=command.output,
        artifact_refs=command.artifact_refs,
        parent_attempt_id=command.parent_attempt_id,
        idempotency_key=idempotency_key,
    )
    _prevent_storage(response)
    return result


@router.post(
    "/{activity_id}/self-review",
    response_model=SelfReviewResponse,
)
async def submit_activity_self_review(
    activity_id: int,
    command: SelfReviewCommand,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ActivityService, Depends(get_activity_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> SelfReviewResponse:
    result = await service.submit_self_review(
        owner_id=owner.owner_id,
        activity_id=activity_id,
        expected_version=command.expected_version,
        main_answer=command.main_answer,
        did_well=command.did_well,
        structure_weakness=command.structure_weakness,
        vague_points=command.vague_points,
        hesitation_points=command.hesitation_points,
        change_next=command.change_next,
        self_score=command.self_score,
        idempotency_key=idempotency_key,
    )
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
    elif isinstance(exc, ActivityUnavailable):
        status, code, title = 503, "activity_dependency_unavailable", "Activity service unavailable"
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
