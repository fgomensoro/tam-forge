"""Application ports and immutable projections for roadmap workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import ParsedRoadmap


class RoadmapWorkflowError(Exception):
    """Base error safe to map to a public roadmap problem response."""


class ImportConflict(RoadmapWorkflowError):
    """An idempotency key was reused for different package content."""


class RoadmapNotFound(RoadmapWorkflowError):
    """The owner-scoped import or version does not exist."""


class ActivationNotEligible(RoadmapWorkflowError):
    """A roadmap version cannot be activated yet."""


_MIRROR_CODES = frozenset(
    {
        "storage_unavailable",
        "write_failed",
        "conflict",
        "permission_denied",
        "invalid_reference",
        "internal_error",
    }
)


class MirrorFailure(RoadmapWorkflowError):
    """A provider failure reduced to a closed, non-sensitive machine code."""

    def __init__(self, code: str) -> None:
        if code not in _MIRROR_CODES:
            raise ValueError("invalid roadmap mirror failure code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class RoadmapImportRecord:
    id: int
    owner_id: int
    source_id: int
    source_key: str
    package_hash: str
    object_key: str
    status: str
    validation_report: dict[str, object]
    semantic_diff: dict[str, object]
    idempotency_key: str
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class CreateImportResult:
    record: RoadmapImportRecord
    created: bool


@dataclass(frozen=True, slots=True)
class RoadmapVersionRecord:
    id: int
    owner_id: int
    source_id: int
    version_key: str
    version_number: int
    month_number: int
    object_key: str
    content_hash: str
    manifest: dict[str, object]
    normalized_payload: dict[str, object]
    state: str
    mirror_status: str
    mirror_ref: str | None
    mirror_error_code: str | None


@dataclass(frozen=True, slots=True)
class ImportApproval:
    owner_id: int
    import_id: int
    parsed: ParsedRoadmap
    manifest: dict[str, object]
    raw_payload: dict[str, object]
    mirror_required: bool


@dataclass(frozen=True, slots=True)
class MirrorRequest:
    version_id: int
    roadmap_version: str
    files: dict[str, bytes]
    manifest: dict[str, object]


class RoadmapRepository(Protocol):
    async def find_duplicate_import(
        self,
        *,
        owner_id: int,
        source_key: str,
        idempotency_key: str,
        package_hash: str,
    ) -> RoadmapImportRecord | None: ...

    async def create_staged_import(
        self,
        *,
        owner_id: int,
        source_key: str,
        source_name: str,
        source_kind: str,
        package_hash: str,
        object_key: str,
        idempotency_key: str,
    ) -> CreateImportResult: ...

    async def begin_validation(
        self, *, owner_id: int, import_id: int
    ) -> RoadmapImportRecord: ...

    async def finish_validation(
        self,
        *,
        owner_id: int,
        import_id: int,
        validation_report: dict[str, object],
        semantic_diff: dict[str, object],
    ) -> RoadmapImportRecord: ...

    async def reject_validation(
        self,
        *,
        owner_id: int,
        import_id: int,
        validation_report: dict[str, object],
        failure_code: str,
    ) -> RoadmapImportRecord: ...

    async def get_import(
        self, *, owner_id: int, import_id: int
    ) -> RoadmapImportRecord | None: ...

    async def latest_normalized_payload(
        self, *, owner_id: int, source_id: int
    ) -> dict[str, object] | None: ...

    async def approve_import(self, approval: ImportApproval) -> RoadmapVersionRecord: ...

    async def get_version(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord | None: ...

    async def list_versions(self, *, owner_id: int) -> tuple[RoadmapVersionRecord, ...]: ...

    async def begin_mirror(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord: ...

    async def finish_mirror(
        self, *, owner_id: int, version_id: int, mirror_ref: str
    ) -> RoadmapVersionRecord: ...

    async def fail_mirror(
        self, *, owner_id: int, version_id: int, error_code: str
    ) -> RoadmapVersionRecord: ...

    async def activate_version(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord: ...


class RoadmapMirror(Protocol):
    enabled: bool

    async def mirror(self, request: MirrorRequest) -> str: ...
