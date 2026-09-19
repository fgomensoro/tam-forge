"""Shadowing clip endpoints: the clips themselves and the signed upload and download of
each clip's excerpt. The excerpt bytes never pass through this process."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..database import get_db_session
from ..storage.dependencies import get_object_store
from ..storage.models import ObjectStoreError
from .schemas import (
    ExcerptConfirmCommand,
    ExcerptDownloadResponse,
    ExcerptUploadCommand,
    ExcerptUploadResponse,
    ShadowingClipCommand,
    ShadowingClipPage,
    ShadowingClipResponse,
)
from .service import (
    ShadowingClipService,
    ShadowingConflict,
    ShadowingInvalid,
    ShadowingNotFound,
    ShadowingUnavailable,
)

router = APIRouter(prefix="/api/v1/shadowing-clips", tags=["shadowing"])


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def get_shadowing_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ShadowingClipService:
    try:
        object_store = get_object_store(request)
    except (ObjectStoreError, ValueError):
        raise ShadowingUnavailable("the excerpt store is unavailable") from None
    return ShadowingClipService(session, object_store)


@router.get("", response_model=ShadowingClipPage)
async def list_shadowing_clips(
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ShadowingClipPage:
    result = await service.list(owner_id=owner.owner_id)
    _prevent_storage(response)
    return result


@router.post("", response_model=ShadowingClipResponse, status_code=201)
async def create_shadowing_clip(
    command: ShadowingClipCommand,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ShadowingClipResponse:
    """Create the clip without its media. The excerpt follows through upload and confirm."""
    result = await service.create(owner_id=owner.owner_id, command=command)
    _prevent_storage(response)
    return result


@router.get("/{clip_id}", response_model=ShadowingClipResponse)
async def get_shadowing_clip(
    clip_id: int,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ShadowingClipResponse:
    result = await service.get(owner_id=owner.owner_id, clip_id=clip_id)
    _prevent_storage(response)
    return result


@router.put("/{clip_id}", response_model=ShadowingClipResponse)
async def replace_shadowing_clip(
    clip_id: int,
    command: ShadowingClipCommand,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ShadowingClipResponse:
    """Replace everything the learner decides about the clip; the excerpt is untouched."""
    result = await service.replace(owner_id=owner.owner_id, clip_id=clip_id, command=command)
    _prevent_storage(response)
    return result


@router.delete("/{clip_id}", status_code=204)
async def delete_shadowing_clip(
    clip_id: int,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> Response:
    await service.delete(owner_id=owner.owner_id, clip_id=clip_id)
    response = Response(status_code=204)
    _prevent_storage(response)
    return response


@router.post("/{clip_id}/excerpt/upload", response_model=ExcerptUploadResponse)
async def presign_shadowing_excerpt(
    clip_id: int,
    command: ExcerptUploadCommand,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ExcerptUploadResponse:
    """A signed PUT for exactly the declared bytes. Send every returned header with it."""
    result = await service.presign_excerpt(
        owner_id=owner.owner_id, clip_id=clip_id, command=command
    )
    _prevent_storage(response)
    return result


@router.post("/{clip_id}/excerpt/confirm", response_model=ShadowingClipResponse)
async def confirm_shadowing_excerpt(
    clip_id: int,
    command: ExcerptConfirmCommand,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> ShadowingClipResponse:
    """Attach the uploaded excerpt to the clip. Safe to repeat for the same bytes."""
    result = await service.confirm_excerpt(
        owner_id=owner.owner_id, clip_id=clip_id, command=command
    )
    _prevent_storage(response)
    return result


@router.get("/{clip_id}/excerpt/download", response_model=ExcerptDownloadResponse)
async def download_shadowing_excerpt(
    clip_id: int,
    response: Response,
    service: Annotated[ShadowingClipService, Depends(get_shadowing_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> ExcerptDownloadResponse:
    result = await service.excerpt_download(owner_id=owner.owner_id, clip_id=clip_id)
    _prevent_storage(response)
    return result


def shadowing_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, ShadowingNotFound):
        status, code, title = 404, "shadowing_clip_not_found", "Shadowing clip not found"
    elif isinstance(exc, ShadowingInvalid):
        status, code, title = 422, "invalid_shadowing_command", "Invalid shadowing command"
    elif isinstance(exc, ShadowingConflict):
        status, code, title = 409, "shadowing_conflict", "Shadowing clip already has its excerpt"
    elif isinstance(exc, ShadowingUnavailable):
        status, code, title = 503, "shadowing_unavailable", "Shadowing unavailable"
    else:
        status, code, title = 500, "shadowing_error", "Shadowing operation failed"
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


async def shadowing_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return shadowing_problem_response(exc)


__all__ = [
    "get_shadowing_service",
    "router",
    "shadowing_exception_handler",
    "shadowing_problem_response",
]
