"""Roadmap import orchestration with explicit approval and activation gates."""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from collections.abc import AsyncIterator, Iterator, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from ..evidence.config_models import ConfigBundle
from ..storage.models import ObjectIntegrityError, build_object_key
from ..storage.ports import ObjectStore
from .contracts import (
    NormalizedCorrectionSelection,
    NormalizedExitCriterion,
    NormalizedProcedureStep,
    NormalizedResource,
    NormalizedTask,
    NormalizedTaskContract,
    ParsedRoadmap,
)
from .diff import diff_roadmaps
from .package import inspect_zip_stream
from .parser import RoadmapParseError, parse_roadmap
from .ports import (
    ImportApproval,
    ImportConflict,
    MirrorFailure,
    MirrorRequest,
    RoadmapImportRecord,
    RoadmapMirror,
    RoadmapNotFound,
    RoadmapRepository,
    RoadmapVersionRecord,
    RoadmapWorkflowError,
)
from .schemas import InspectedRoadmapPackage, ValidationIssue

_SAFE_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_SOURCE_KEY = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class InvalidImportRequest(RoadmapWorkflowError):
    """Import metadata or package bytes violate a bounded public contract."""


class ImportNotApprovable(RoadmapWorkflowError):
    """An import has not passed validation or was already consumed."""


class MirrorNotRetryable(RoadmapWorkflowError):
    """A version has no retryable mirror failure."""


def _file_chunks(path: Path, chunk_bytes: int = 64 * 1024) -> Iterator[bytes]:
    with path.open("rb") as source:
        while chunk := source.read(chunk_bytes):
            yield chunk


async def _async_file_chunks(path: Path, chunk_bytes: int = 64 * 1024) -> AsyncIterator[bytes]:
    with path.open("rb") as source:
        while chunk := source.read(chunk_bytes):
            yield chunk


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    for chunk in _file_chunks(path):
        digest.update(chunk)
    return digest.hexdigest()


def _canonical_folder_zip(package: InspectedRoadmapPackage) -> tuple[Path, str]:
    archive_path = package.staging_root / "folder-snapshot.zip"
    with zipfile.ZipFile(
        archive_path,
        mode="x",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for item in sorted(package.files, key=lambda value: value.manifest.path):
            info = zipfile.ZipInfo(item.manifest.path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            with item.staged_path.open("rb") as source, archive.open(info, "w") as output:
                shutil.copyfileobj(source, output, length=64 * 1024)
    return archive_path, _sha256_file(archive_path)


def _snapshot(package: InspectedRoadmapPackage, package_kind: str) -> tuple[Path, str]:
    if package_kind == "zip":
        if package.archive_path is None or package.archive_sha256 is None:
            raise InvalidImportRequest("ZIP package bytes are unavailable")
        return package.archive_path, package.archive_sha256
    if package_kind == "folder_entries":
        if not package.files:
            raise InvalidImportRequest("folder package bytes are unavailable")
        return _canonical_folder_zip(package)
    raise InvalidImportRequest("package_kind must be zip or folder_entries")


def _issue_payload(issue: ValidationIssue) -> dict[str, object]:
    return {
        "code": issue.code,
        "path": issue.path,
        "severity": issue.severity,
        "message": issue.message,
    }


def _empty_roadmap(version: str) -> ParsedRoadmap:
    return ParsedRoadmap(
        schema_version=1,
        roadmap_version=version,
        tasks=(),
        contracts=(),
        resources=(),
        exit_criteria=(),
        normalized_hash="0" * 64,
    )


def _tuple_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("stored roadmap list is invalid")
    return tuple(value)


def _procedure(value: object) -> tuple[NormalizedProcedureStep, ...]:
    if not isinstance(value, list):
        raise ValueError("stored roadmap procedure is invalid")
    result: list[NormalizedProcedureStep] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("stored roadmap procedure is invalid")
        phase = item.get("phase")
        minutes = item.get("minutes")
        requirement = item.get("requirement")
        if (
            not isinstance(phase, str)
            or (minutes is not None and not isinstance(minutes, int))
            or not isinstance(requirement, str)
        ):
            raise ValueError("stored roadmap procedure is invalid")
        result.append(NormalizedProcedureStep(phase, minutes, requirement))
    return tuple(result)


def _correction(value: object) -> NormalizedCorrectionSelection | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("stored correction selection is invalid")
    return NormalizedCorrectionSelection(
        source=str(value["source"]),
        maximum_items=int(value["maximum_items"]),
        allowed_kinds=_tuple_strings(value["allowed_kinds"]),
        inherits_core_prompt=bool(value["inherits_core_prompt"]),
        inherits_original_exercise=bool(value["inherits_original_exercise"]),
        inherits_original_mapping_version=bool(value["inherits_original_mapping_version"]),
        no_attempt_c=bool(value["no_attempt_c"]),
        skill_level_effect=str(value["skill_level_effect"]),
    )


def _parsed_from_payload(value: Mapping[str, object]) -> ParsedRoadmap:
    tasks_payload = value.get("tasks")
    resources_payload = value.get("resources")
    exits_payload = value.get("exit_criteria")
    if (
        not isinstance(tasks_payload, list)
        or not isinstance(resources_payload, list)
        or not isinstance(exits_payload, list)
    ):
        raise ValueError("stored normalized roadmap payload is invalid")
    tasks: list[NormalizedTask] = []
    for raw in tasks_payload:
        if not isinstance(raw, dict):
            raise ValueError("stored normalized task is invalid")
        exercise = raw.get("exercise_type")
        mapping = raw.get("mapping_version")
        tasks.append(
            NormalizedTask(
                stable_id=str(raw["stable_id"]),
                month=int(raw["month"]),
                week=int(raw["week"]),
                day=int(raw["day"]),
                block=str(raw["block"]),
                order=int(raw["order"]),
                source_path=str(raw["source_path"]),
                source_heading=str(raw["source_heading"]),
                exercise_type=None if exercise is None else str(exercise),
                mapping_version=None if mapping is None else str(mapping),
                required=bool(raw["required"]),
                timebox_minutes=int(raw["timebox_minutes"]),
                objective=str(raw["objective"]),
                required_output=_tuple_strings(raw["required_output"]),
                pass_criteria=_tuple_strings(raw["pass_criteria"]),
                evidence_requirements=_tuple_strings(raw["evidence_requirements"]),
                procedure=_procedure(raw["procedure"]),
                constraints=_tuple_strings(raw["constraints"]),
                correction_selection=_correction(raw.get("correction_selection")),
                allowed_ai_role=str(raw["allowed_ai_role"]),
            )
        )
    contracts = tuple(
        NormalizedTaskContract(
            stable_id=task.stable_id,
            required_output=task.required_output,
            pass_criteria=task.pass_criteria,
            evidence_requirements=task.evidence_requirements,
            procedure=task.procedure,
            constraints=task.constraints,
            correction_selection=task.correction_selection,
        )
        for task in tasks
    )
    resources = tuple(
        NormalizedResource(
            key=str(raw["key"]),
            kind="external" if raw["kind"] == "external" else "local",
            labels=_tuple_strings(raw["labels"]),
            source_paths=_tuple_strings(raw["source_paths"]),
        )
        for raw in resources_payload
        if isinstance(raw, dict)
    )
    exits = tuple(
        NormalizedExitCriterion(
            text=str(raw["text"]),
            source_paths=_tuple_strings(raw["source_paths"]),
        )
        for raw in exits_payload
        if isinstance(raw, dict)
    )
    schema_version = value.get("schema_version")
    if not isinstance(schema_version, int):
        raise ValueError("stored roadmap schema version is invalid")
    return ParsedRoadmap(
        schema_version=schema_version,
        roadmap_version=str(value["roadmap_version"]),
        tasks=tuple(tasks),
        contracts=contracts,
        resources=resources,
        exit_criteria=exits,
        normalized_hash=str(value["normalized_hash"]),
    )


class RoadmapService:
    """Coordinates storage, persistence, mirroring, and explicit activation."""

    def __init__(
        self,
        *,
        config: ConfigBundle,
        repository: RoadmapRepository,
        object_store: ObjectStore,
        mirror: RoadmapMirror | None,
    ) -> None:
        self._config = config
        self._repository = repository
        self._object_store = object_store
        self._mirror = mirror

    async def stage_package(
        self,
        *,
        owner_id: int,
        source_key: str,
        source_name: str,
        source_kind: str,
        package_kind: str,
        idempotency_key: str,
        package: InspectedRoadmapPackage,
    ) -> RoadmapImportRecord:
        if owner_id <= 0 or not _SAFE_SOURCE_KEY.fullmatch(source_key):
            raise InvalidImportRequest("roadmap source is invalid")
        if source_kind not in {"obsidian", "package", "manual"}:
            raise InvalidImportRequest("roadmap source kind is invalid")
        if not source_name.strip() or len(source_name.encode()) > 256:
            raise InvalidImportRequest("roadmap source name is invalid")
        if not _SAFE_IDEMPOTENCY.fullmatch(idempotency_key):
            raise InvalidImportRequest("Idempotency-Key is invalid")

        snapshot_path, package_hash = _snapshot(package, package_kind)
        duplicate = await self._repository.find_duplicate_import(
            owner_id=owner_id,
            source_key=source_key,
            idempotency_key=idempotency_key,
            package_hash=package_hash,
        )
        if duplicate is not None:
            if (
                duplicate.idempotency_key == idempotency_key
                and (
                    duplicate.source_key != source_key
                    or duplicate.package_hash != package_hash
                )
            ):
                raise ImportConflict("Idempotency-Key was already used for different content")
            return duplicate

        object_key = build_object_key(
            artifact_class="roadmap-source",
            owner_id=str(owner_id),
            logical_id=f"import-{package_hash[:24]}",
            sha256=package_hash,
        )
        await self._object_store.put_immutable(
            key=object_key,
            body=_async_file_chunks(snapshot_path),
            sha256=package_hash,
            content_type="application/zip",
            metadata={"artifact": "roadmap-source", "package-kind": package_kind},
        )
        created = await self._repository.create_staged_import(
            owner_id=owner_id,
            source_key=source_key,
            source_name=source_name,
            source_kind=source_kind,
            package_hash=package_hash,
            object_key=object_key,
            idempotency_key=idempotency_key,
        )
        record = created.record
        if not created.created:
            return record
        await self._repository.begin_validation(owner_id=owner_id, import_id=record.id)
        if package.issues:
            return await self._repository.reject_validation(
                owner_id=owner_id,
                import_id=record.id,
                validation_report={
                    "schema_version": 1,
                    "accepted": False,
                    "issues": [_issue_payload(item) for item in package.issues],
                },
                failure_code="invalid_package",
            )
        try:
            files = {item.manifest.path: item.staged_path.read_bytes() for item in package.files}
            parsed = parse_roadmap(files=files, config=self._config)
        except (RoadmapParseError, UnicodeError, ValueError) as exc:
            return await self._repository.reject_validation(
                owner_id=owner_id,
                import_id=record.id,
                validation_report={
                    "schema_version": 1,
                    "accepted": False,
                    "issues": [
                        {
                            "code": "roadmap_validation_failed",
                            "path": None,
                            "severity": "error",
                            "message": str(exc),
                        }
                    ],
                },
                failure_code="validation_failed",
            )
        previous_payload = await self._repository.latest_normalized_payload(
            owner_id=owner_id,
            source_id=record.source_id,
        )
        before = (
            _parsed_from_payload(previous_payload)
            if previous_payload is not None
            else _empty_roadmap(parsed.roadmap_version)
        )
        semantic_diff = cast(dict[str, object], diff_roadmaps(before, parsed).to_dict())
        return await self._repository.finish_validation(
            owner_id=owner_id,
            import_id=record.id,
            validation_report={
                "schema_version": 1,
                "accepted": True,
                "normalized_hash": parsed.normalized_hash,
                "task_count": len(parsed.tasks),
                "resource_count": len(parsed.resources),
                "exit_criterion_count": len(parsed.exit_criteria),
                "issues": [],
            },
            semantic_diff=semantic_diff,
        )

    async def get_import(self, *, owner_id: int, import_id: int) -> RoadmapImportRecord:
        record = await self._repository.get_import(owner_id=owner_id, import_id=import_id)
        if record is None:
            raise RoadmapNotFound("roadmap import was not found")
        return record

    async def approve_import(self, *, owner_id: int, import_id: int) -> RoadmapVersionRecord:
        record = await self.get_import(owner_id=owner_id, import_id=import_id)
        if record.status != "validated":
            raise ImportNotApprovable("roadmap import is not validated")
        stored = await self._object_store.stat(record.object_key)
        if stored is None or stored.sha256 != record.package_hash:
            raise ObjectIntegrityError("immutable roadmap snapshot is unavailable")
        with await self._open_package(record.object_key) as package:
            if not package.accepted or package.manifest is None:
                raise ImportNotApprovable("stored roadmap snapshot is invalid")
            files = {item.manifest.path: item.staged_path.read_bytes() for item in package.files}
            parsed = parse_roadmap(files=files, config=self._config)
            if record.validation_report.get("normalized_hash") != parsed.normalized_hash:
                raise ObjectIntegrityError("stored roadmap does not match validated preview")
            manifest = package.manifest.to_dict()
            version = await self._repository.approve_import(
                ImportApproval(
                    owner_id=owner_id,
                    import_id=import_id,
                    parsed=parsed,
                    manifest=manifest,
                    raw_payload={
                        "schema_version": 1,
                        "package_hash": record.package_hash,
                        "manifest": manifest,
                    },
                    mirror_required=self._mirror is not None and self._mirror.enabled,
                )
            )
            if self._mirror is None or not self._mirror.enabled:
                return version
            return await self._run_mirror(version=version, files=files, manifest=manifest)

    async def retry_mirror(self, *, owner_id: int, version_id: int) -> RoadmapVersionRecord:
        version = await self._repository.get_version(owner_id=owner_id, version_id=version_id)
        if version is None:
            raise RoadmapNotFound("roadmap version was not found")
        if version.mirror_status != "failed" or self._mirror is None or not self._mirror.enabled:
            raise MirrorNotRetryable("roadmap mirror is not retryable")
        with await self._open_package(version.object_key) as package:
            if not package.accepted or package.manifest is None:
                raise MirrorNotRetryable("stored roadmap snapshot is invalid")
            files = {item.manifest.path: item.staged_path.read_bytes() for item in package.files}
            manifest = package.manifest.to_dict()
            return await self._run_mirror(version=version, files=files, manifest=manifest)

    async def _run_mirror(
        self,
        *,
        version: RoadmapVersionRecord,
        files: dict[str, bytes],
        manifest: dict[str, object],
    ) -> RoadmapVersionRecord:
        assert self._mirror is not None
        await self._repository.begin_mirror(owner_id=version.owner_id, version_id=version.id)
        try:
            mirror_ref = await self._mirror.mirror(
                MirrorRequest(
                    version_id=version.id,
                    roadmap_version=version.version_key,
                    files=files,
                    manifest=manifest,
                )
            )
        except MirrorFailure as exc:
            return await self._repository.fail_mirror(
                owner_id=version.owner_id,
                version_id=version.id,
                error_code=exc.code,
            )
        except Exception:
            return await self._repository.fail_mirror(
                owner_id=version.owner_id,
                version_id=version.id,
                error_code="internal_error",
            )
        return await self._repository.finish_mirror(
            owner_id=version.owner_id,
            version_id=version.id,
            mirror_ref=mirror_ref,
        )

    async def activate_version(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord:
        return await self._repository.activate_version(owner_id=owner_id, version_id=version_id)

    async def list_versions(self, *, owner_id: int) -> tuple[RoadmapVersionRecord, ...]:
        return await self._repository.list_versions(owner_id=owner_id)

    async def _open_package(self, object_key: str) -> InspectedRoadmapPackage:
        temporary = TemporaryDirectory(prefix="tamforge-roadmap-load-")
        path = Path(temporary.name) / "snapshot.zip"
        try:
            async with self._object_store.open(object_key) as stream:
                with path.open("xb") as output:
                    async for chunk in stream:
                        output.write(chunk)
            package = inspect_zip_stream(_file_chunks(path))
        finally:
            temporary.cleanup()
        return package
