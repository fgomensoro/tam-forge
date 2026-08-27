"""Authenticated HTTP routes for staged roadmap imports and explicit activation."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.dependencies import get_authenticated_owner, require_csrf_owner
from ..auth.schemas import AuthenticatedOwner, ProblemResponse
from ..config import Settings
from ..database import get_db_session
from ..evidence.config_loader import load_config_bundle
from ..storage.dependencies import get_object_store
from ..storage.models import ObjectStoreError
from ..storage.ports import ObjectStore
from .github_mirror import GitHubRoadmapMirror
from .package import inspect_browser_folder, inspect_zip_stream
from .ports import (
    ActivationNotEligible,
    ImportConflict,
    RoadmapImportRecord,
    RoadmapNotFound,
    RoadmapVersionRecord,
)
from .repository import SqlAlchemyRoadmapRepository
from .schemas import BrowserFolderEntry
from .service import (
    ImportNotApprovable,
    InvalidImportRequest,
    MirrorNotRetryable,
    RoadmapService,
)

router = APIRouter(prefix="/api/v1", tags=["roadmaps"])


class RoadmapImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    status: str
    validation_report: dict[str, object]
    semantic_diff: dict[str, object]
    failure_code: str | None


class RoadmapVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    version_key: str
    version_number: int
    month_number: int
    state: str
    mirror_status: str
    mirror_ref: str | None
    mirror_error_code: str | None


def _prevent_storage(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"


def _import_response(item: RoadmapImportRecord) -> RoadmapImportResponse:
    return RoadmapImportResponse(
        id=item.id,
        status=item.status,
        validation_report=item.validation_report,
        semantic_diff=item.semantic_diff,
        failure_code=item.failure_code,
    )


def _version_response(item: RoadmapVersionRecord) -> RoadmapVersionResponse:
    return RoadmapVersionResponse(
        id=item.id,
        version_key=item.version_key,
        version_number=item.version_number,
        month_number=item.month_number,
        state=item.state,
        mirror_status=item.mirror_status,
        mirror_ref=item.mirror_ref,
        mirror_error_code=item.mirror_error_code,
    )


def _upload_chunks(upload: UploadFile, chunk_bytes: int = 64 * 1024) -> Iterator[bytes]:
    while chunk := upload.file.read(chunk_bytes):
        yield chunk


def get_roadmap_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SqlAlchemyRoadmapRepository:
    return SqlAlchemyRoadmapRepository(session)


def get_roadmap_service(
    request: Request,
    repository: Annotated[SqlAlchemyRoadmapRepository, Depends(get_roadmap_repository)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
) -> RoadmapService:
    settings = cast(Settings, request.app.state.settings)
    config = getattr(request.app.state, "roadmap_config", None)
    if config is None:
        config = load_config_bundle(settings.roadmap_config_dir)
        request.app.state.roadmap_config = config
    token = settings.github_roadmap_mirror_token.get_secret_value()
    mirror = None
    if token and settings.github_roadmap_mirror_repository:
        mirror = GitHubRoadmapMirror(
            token=token,
            repository=settings.github_roadmap_mirror_repository,
            branch=settings.github_roadmap_mirror_branch,
            base_branch=settings.github_roadmap_mirror_base_branch,
        )
    return RoadmapService(
        config=config,
        repository=repository,
        object_store=object_store,
        mirror=mirror,
    )


@router.post(
    "/roadmap-imports",
    response_model=RoadmapImportResponse,
    status_code=201,
)
async def create_roadmap_import(
    response: Response,
    service: Annotated[RoadmapService, Depends(get_roadmap_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
    package_kind: Annotated[Literal["zip", "folder_entries"], Form()],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    package: Annotated[UploadFile | None, File()] = None,
    paths: Annotated[list[str] | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> RoadmapImportResponse:
    uploads: list[UploadFile] = []
    try:
        if package_kind == "zip":
            if package is None or files or paths:
                raise InvalidImportRequest("ZIP import requires exactly one package file")
            uploads.append(package)
            inspected = inspect_zip_stream(_upload_chunks(package))
        else:
            uploads.extend(files or [])
            if package is not None or not files or not paths or len(files) != len(paths):
                raise InvalidImportRequest("folder import requires matching paths and files")
            inspected = inspect_browser_folder(
                BrowserFolderEntry(path=path, chunks=_upload_chunks(upload))
                for path, upload in zip(paths, files, strict=True)
            )
        with inspected:
            result = await service.stage_package(
                owner_id=owner.owner_id,
                source_key="obsidian-main",
                source_name="TAM Roadmap",
                source_kind="obsidian",
                package_kind=package_kind,
                idempotency_key=idempotency_key,
                package=inspected,
            )
    finally:
        for upload in uploads:
            await upload.close()
    _prevent_storage(response)
    return _import_response(result)


@router.get("/roadmap-imports/{import_id}", response_model=RoadmapImportResponse)
async def get_roadmap_import(
    import_id: int,
    response: Response,
    service: Annotated[RoadmapService, Depends(get_roadmap_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> RoadmapImportResponse:
    result = await service.get_import(owner_id=owner.owner_id, import_id=import_id)
    _prevent_storage(response)
    return _import_response(result)


@router.post(
    "/roadmap-imports/{import_id}/approve",
    response_model=RoadmapVersionResponse,
)
async def approve_roadmap_import(
    import_id: int,
    response: Response,
    service: Annotated[RoadmapService, Depends(get_roadmap_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> RoadmapVersionResponse:
    result = await service.approve_import(owner_id=owner.owner_id, import_id=import_id)
    _prevent_storage(response)
    return _version_response(result)


@router.post(
    "/roadmap-imports/{version_id}/mirror/retry",
    response_model=RoadmapVersionResponse,
)
async def retry_roadmap_mirror(
    version_id: int,
    response: Response,
    service: Annotated[RoadmapService, Depends(get_roadmap_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> RoadmapVersionResponse:
    result = await service.retry_mirror(owner_id=owner.owner_id, version_id=version_id)
    _prevent_storage(response)
    return _version_response(result)


@router.get("/roadmap-versions", response_model=list[RoadmapVersionResponse])
async def list_roadmap_versions(
    response: Response,
    service: Annotated[RoadmapService, Depends(get_roadmap_service)],
    owner: Annotated[AuthenticatedOwner, Depends(get_authenticated_owner)],
) -> list[RoadmapVersionResponse]:
    result = await service.list_versions(owner_id=owner.owner_id)
    _prevent_storage(response)
    return [_version_response(item) for item in result]


@router.post(
    "/roadmap-versions/{version_id}/activate",
    response_model=RoadmapVersionResponse,
)
async def activate_roadmap_version(
    version_id: int,
    response: Response,
    service: Annotated[RoadmapService, Depends(get_roadmap_service)],
    owner: Annotated[AuthenticatedOwner, Depends(require_csrf_owner)],
) -> RoadmapVersionResponse:
    result = await service.activate_version(owner_id=owner.owner_id, version_id=version_id)
    _prevent_storage(response)
    return _version_response(result)


def roadmap_problem_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, RoadmapNotFound):
        status, code, title = 404, "roadmap_not_found", "Roadmap not found"
    elif isinstance(exc, InvalidImportRequest):
        status, code, title = 422, "invalid_roadmap_import", "Invalid roadmap import"
    elif isinstance(
        exc,
        (ImportConflict, ImportNotApprovable, ActivationNotEligible, MirrorNotRetryable),
    ):
        status, code, title = 409, "roadmap_state_conflict", "Roadmap state conflict"
    elif isinstance(exc, ObjectStoreError):
        status, code, title = 503, "roadmap_storage_unavailable", "Roadmap storage unavailable"
    else:
        status, code, title = 500, "roadmap_error", "Roadmap operation failed"
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


async def roadmap_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return roadmap_problem_response(exc)
