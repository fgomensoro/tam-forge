"""Transactional PostgreSQL persistence for immutable roadmap workflows."""

from __future__ import annotations

import hashlib
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import transaction_scope
from ..models.base import utc_now
from ..notifications.models import OutboxEvent
from .contracts import ParsedRoadmap
from .models import (
    CurriculumNode,
    ExitCriterion,
    MonthExitReview,
    PassCriterion,
    Resource,
    RoadmapImport,
    RoadmapSource,
    RoadmapVersion,
    TaskDefinition,
)
from .ports import (
    ActivationNotEligible,
    CreateImportResult,
    ImportApproval,
    ImportConflict,
    RoadmapImportRecord,
    RoadmapNotFound,
    RoadmapVersionRecord,
)


class SqlAlchemyRoadmapRepository:
    """Owner-scoped repository with short, explicit transaction boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_duplicate_import(
        self,
        *,
        owner_id: int,
        source_key: str,
        idempotency_key: str,
        package_hash: str,
    ) -> RoadmapImportRecord | None:
        idempotency_row = (
            await self._session.execute(
                select(RoadmapImport, RoadmapSource.source_key)
                .join(
                    RoadmapSource,
                    (RoadmapSource.owner_id == RoadmapImport.owner_id)
                    & (RoadmapSource.id == RoadmapImport.source_id),
                )
                .where(RoadmapImport.owner_id == owner_id)
                .where(RoadmapImport.idempotency_key == idempotency_key)
            )
        ).first()
        package_row = None
        if idempotency_row is None:
            package_row = (
                await self._session.execute(
                    select(RoadmapImport, RoadmapSource.source_key)
                    .join(
                        RoadmapSource,
                        (RoadmapSource.owner_id == RoadmapImport.owner_id)
                        & (RoadmapSource.id == RoadmapImport.source_id),
                    )
                    .where(RoadmapImport.owner_id == owner_id)
                    .where(RoadmapSource.source_key == source_key)
                    .where(RoadmapImport.package_hash == bytes.fromhex(package_hash))
                )
            ).first()
        row = idempotency_row or package_row
        result = self._to_import(row[0], row[1]) if row is not None else None
        await self._session.rollback()
        return result

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
    ) -> CreateImportResult:
        digest = bytes.fromhex(package_hash)
        async with transaction_scope(self._session):
            await self._session.execute(
                select(func.pg_advisory_xact_lock(owner_id, func.hashtext(source_key)))
            )
            await self._session.execute(
                insert(RoadmapSource)
                .values(
                    owner_id=owner_id,
                    source_key=source_key,
                    name=source_name,
                    source_kind=source_kind,
                )
                .on_conflict_do_nothing(
                    index_elements=[RoadmapSource.owner_id, RoadmapSource.source_key]
                )
            )
            source = (
                await self._session.execute(
                    select(RoadmapSource)
                    .where(RoadmapSource.owner_id == owner_id)
                    .where(RoadmapSource.source_key == source_key)
                    .with_for_update()
                )
            ).scalar_one()
            existing_by_key = (
                await self._session.execute(
                    select(RoadmapImport)
                    .where(RoadmapImport.owner_id == owner_id)
                    .where(RoadmapImport.idempotency_key == idempotency_key)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if existing_by_key is not None:
                if (
                    existing_by_key.source_id != source.id
                    or existing_by_key.package_hash != digest
                ):
                    raise ImportConflict(
                        "Idempotency-Key was already used for different content"
                    )
                return CreateImportResult(
                    record=self._to_import(existing_by_key, source.source_key),
                    created=False,
                )
            existing_by_hash = (
                await self._session.execute(
                    select(RoadmapImport)
                    .where(RoadmapImport.owner_id == owner_id)
                    .where(RoadmapImport.source_id == source.id)
                    .where(RoadmapImport.package_hash == digest)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if existing_by_hash is not None:
                return CreateImportResult(
                    record=self._to_import(existing_by_hash, source.source_key),
                    created=False,
                )
            item = RoadmapImport(
                owner_id=owner_id,
                source_id=source.id,
                package_hash=digest,
                object_key=object_key,
                status="staged",
                validation_report={},
                semantic_diff={},
                idempotency_key=idempotency_key,
                failure_code=None,
                started_at=None,
                completed_at=None,
            )
            self._session.add(item)
            await self._session.flush()
            result = self._to_import(item, source.source_key)
        return CreateImportResult(record=result, created=True)

    async def begin_validation(
        self, *, owner_id: int, import_id: int
    ) -> RoadmapImportRecord:
        async with transaction_scope(self._session):
            item, source_key = await self._locked_import(owner_id, import_id)
            item.status = "validating"
            item.started_at = utc_now()
            await self._session.flush()
            result = self._to_import(item, source_key)
        return result

    async def finish_validation(
        self,
        *,
        owner_id: int,
        import_id: int,
        validation_report: dict[str, object],
        semantic_diff: dict[str, object],
    ) -> RoadmapImportRecord:
        async with transaction_scope(self._session):
            item, source_key = await self._locked_import(owner_id, import_id)
            item.validation_report = cast(dict[str, Any], validation_report)
            item.semantic_diff = cast(dict[str, Any], semantic_diff)
            item.status = "validated"
            item.completed_at = utc_now()
            await self._session.flush()
            result = self._to_import(item, source_key)
        return result

    async def reject_validation(
        self,
        *,
        owner_id: int,
        import_id: int,
        validation_report: dict[str, object],
        failure_code: str,
    ) -> RoadmapImportRecord:
        async with transaction_scope(self._session):
            item, source_key = await self._locked_import(owner_id, import_id)
            item.validation_report = cast(dict[str, Any], validation_report)
            item.failure_code = failure_code
            item.status = "rejected"
            item.completed_at = utc_now()
            await self._session.flush()
            result = self._to_import(item, source_key)
        return result

    async def get_import(
        self, *, owner_id: int, import_id: int
    ) -> RoadmapImportRecord | None:
        row = (
            await self._session.execute(
                select(RoadmapImport, RoadmapSource.source_key)
                .join(
                    RoadmapSource,
                    (RoadmapSource.owner_id == RoadmapImport.owner_id)
                    & (RoadmapSource.id == RoadmapImport.source_id),
                )
                .where(RoadmapImport.owner_id == owner_id)
                .where(RoadmapImport.id == import_id)
            )
        ).first()
        result = self._to_import(row[0], row[1]) if row is not None else None
        await self._session.rollback()
        return result

    async def latest_normalized_payload(
        self, *, owner_id: int, source_id: int
    ) -> dict[str, object] | None:
        value = (
            await self._session.execute(
                select(RoadmapVersion.normalized_payload)
                .where(RoadmapVersion.owner_id == owner_id)
                .where(RoadmapVersion.source_id == source_id)
                .order_by(RoadmapVersion.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        await self._session.rollback()
        return cast(dict[str, object] | None, value)

    async def approve_import(self, approval: ImportApproval) -> RoadmapVersionRecord:
        async with transaction_scope(self._session):
            item, _ = await self._locked_import(approval.owner_id, approval.import_id)
            if item.status != "validated":
                raise ImportConflict("roadmap import is not validated")
            source = (
                await self._session.execute(
                    select(RoadmapSource)
                    .where(RoadmapSource.owner_id == approval.owner_id)
                    .where(RoadmapSource.id == item.source_id)
                    .with_for_update()
                )
            ).scalar_one()
            predecessor = (
                await self._session.execute(
                    select(RoadmapVersion)
                    .where(RoadmapVersion.owner_id == approval.owner_id)
                    .where(RoadmapVersion.source_id == item.source_id)
                    .order_by(RoadmapVersion.version_number.desc())
                    .limit(1)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            version_number = 1 if predecessor is None else predecessor.version_number + 1
            parsed = approval.parsed
            version = RoadmapVersion(
                owner_id=approval.owner_id,
                source_id=source.id,
                version_key=parsed.roadmap_version,
                version_number=version_number,
                month_number=parsed.tasks[0].month,
                predecessor_id=None if predecessor is None else predecessor.id,
                content_hash=bytes.fromhex(parsed.normalized_hash),
                object_key=item.object_key,
                manifest=cast(dict[str, Any], approval.manifest),
                raw_payload=cast(dict[str, Any], approval.raw_payload),
                normalized_payload=cast(dict[str, Any], parsed.to_dict()),
                approved_at=None,
                activated_at=None,
                superseded_at=None,
                mirror_status="pending" if approval.mirror_required else "not_required",
                mirror_ref=None,
                mirror_error_code=None,
                state="draft",
            )
            self._session.add(version)
            await self._session.flush()
            await self._persist_curriculum(approval.owner_id, version.id, parsed)
            now = utc_now()
            version.approved_at = now
            version.state = "approved"
            item.status = "imported"
            self._session.add(
                OutboxEvent(
                    owner_id=approval.owner_id,
                    aggregate_type="roadmap",
                    aggregate_id=version.id,
                    event_type="roadmap.version_approved",
                    payload_schema_version=1,
                    payload={"schema_version": 1, "subject_id": version.id},
                    published_at=None,
                    attempts=0,
                    idempotency_key=f"roadmap-version-approved:{version.id}",
                )
            )
            await self._session.flush()
            result = self._to_version(version)
        return result

    async def get_version(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord | None:
        version = (
            await self._session.execute(
                select(RoadmapVersion)
                .where(RoadmapVersion.owner_id == owner_id)
                .where(RoadmapVersion.id == version_id)
            )
        ).scalar_one_or_none()
        result = self._to_version(version) if version is not None else None
        await self._session.rollback()
        return result

    async def list_versions(self, *, owner_id: int) -> tuple[RoadmapVersionRecord, ...]:
        versions = (
            await self._session.execute(
                select(RoadmapVersion)
                .where(RoadmapVersion.owner_id == owner_id)
                .order_by(RoadmapVersion.version_number.desc(), RoadmapVersion.id.desc())
            )
        ).scalars()
        result = tuple(self._to_version(item) for item in versions)
        await self._session.rollback()
        return result

    async def begin_mirror(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord:
        async with transaction_scope(self._session):
            version = await self._locked_version(owner_id, version_id)
            version.mirror_error_code = None
            version.mirror_ref = None
            version.mirror_status = "syncing"
            await self._session.flush()
            result = self._to_version(version)
        return result

    async def finish_mirror(
        self, *, owner_id: int, version_id: int, mirror_ref: str
    ) -> RoadmapVersionRecord:
        async with transaction_scope(self._session):
            version = await self._locked_version(owner_id, version_id)
            version.mirror_ref = mirror_ref
            version.mirror_error_code = None
            version.mirror_status = "synced"
            await self._session.flush()
            result = self._to_version(version)
        return result

    async def fail_mirror(
        self, *, owner_id: int, version_id: int, error_code: str
    ) -> RoadmapVersionRecord:
        async with transaction_scope(self._session):
            version = await self._locked_version(owner_id, version_id)
            version.mirror_ref = None
            version.mirror_error_code = error_code
            version.mirror_status = "failed"
            await self._session.flush()
            result = self._to_version(version)
        return result

    async def activate_version(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord:
        from ..learning.models import LearnerSetting

        async with transaction_scope(self._session):
            versions = tuple(
                (
                    await self._session.execute(
                        select(RoadmapVersion)
                        .where(RoadmapVersion.owner_id == owner_id)
                        .order_by(RoadmapVersion.id)
                        .with_for_update()
                    )
                ).scalars()
            )
            target = next((item for item in versions if item.id == version_id), None)
            if target is None:
                raise RoadmapNotFound("roadmap version was not found")
            if target.state != "approved":
                raise ActivationNotEligible("roadmap version is not approved")
            if target.month_number > 1:
                eligible = (
                    await self._session.execute(
                        select(MonthExitReview.id)
                        .join(
                            RoadmapVersion,
                            (RoadmapVersion.owner_id == MonthExitReview.owner_id)
                            & (RoadmapVersion.id == MonthExitReview.roadmap_version_id),
                        )
                        .where(MonthExitReview.owner_id == owner_id)
                        .where(RoadmapVersion.month_number == target.month_number - 1)
                        .where(MonthExitReview.state == "completed")
                        .where(MonthExitReview.decision == "advance")
                        .where(MonthExitReview.activation_eligible.is_(True))
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if eligible is None:
                    raise ActivationNotEligible(
                        "previous month exit review is not activation eligible"
                    )
            now = utc_now()
            active = next((item for item in versions if item.state == "active"), None)
            if active is not None:
                active.superseded_at = now
                active.state = "superseded"
                await self._session.flush()
            target.activated_at = now
            target.state = "active"
            await self._session.execute(
                update(LearnerSetting)
                .where(LearnerSetting.owner_id == owner_id)
                .values(active_roadmap_version_id=target.id)
            )
            self._session.add(
                OutboxEvent(
                    owner_id=owner_id,
                    aggregate_type="roadmap",
                    aggregate_id=target.id,
                    event_type="roadmap.version_activated",
                    payload_schema_version=1,
                    payload={"schema_version": 1, "subject_id": target.id},
                    published_at=None,
                    attempts=0,
                    idempotency_key=f"roadmap-version-activated:{target.id}",
                )
            )
            await self._session.flush()
            result = self._to_version(target)
        return result

    async def _locked_import(
        self, owner_id: int, import_id: int
    ) -> tuple[RoadmapImport, str]:
        row = (
            await self._session.execute(
                select(RoadmapImport, RoadmapSource.source_key)
                .join(
                    RoadmapSource,
                    (RoadmapSource.owner_id == RoadmapImport.owner_id)
                    & (RoadmapSource.id == RoadmapImport.source_id),
                )
                .where(RoadmapImport.owner_id == owner_id)
                .where(RoadmapImport.id == import_id)
                .with_for_update()
            )
        ).first()
        if row is None:
            raise RoadmapNotFound("roadmap import was not found")
        return row[0], row[1]

    async def _locked_version(self, owner_id: int, version_id: int) -> RoadmapVersion:
        version = (
            await self._session.execute(
                select(RoadmapVersion)
                .where(RoadmapVersion.owner_id == owner_id)
                .where(RoadmapVersion.id == version_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if version is None:
            raise RoadmapNotFound("roadmap version was not found")
        return version

    async def _persist_curriculum(
        self,
        owner_id: int,
        version_id: int,
        parsed: ParsedRoadmap,
    ) -> None:
        month_number = parsed.tasks[0].month
        month_node = CurriculumNode(
            owner_id=owner_id,
            roadmap_version_id=version_id,
            stable_id=f"m{month_number}",
            parent_id=None,
            ordinal=month_number,
            kind="month",
            title=f"Month {month_number}",
            source_path=None,
            source_anchor=None,
        )
        self._session.add(month_node)
        await self._session.flush()
        week_nodes: dict[int, CurriculumNode] = {}
        day_nodes: dict[int, CurriculumNode] = {}
        for task in parsed.tasks:
            if task.week not in week_nodes:
                node = CurriculumNode(
                    owner_id=owner_id,
                    roadmap_version_id=version_id,
                    stable_id=f"m{month_number}-w{task.week}",
                    parent_id=month_node.id,
                    ordinal=task.week,
                    kind="week",
                    title=f"Week {task.week}",
                    source_path=task.source_path,
                    source_anchor=None,
                )
                self._session.add(node)
                await self._session.flush()
                week_nodes[task.week] = node
            if task.day not in day_nodes:
                node = CurriculumNode(
                    owner_id=owner_id,
                    roadmap_version_id=version_id,
                    stable_id=f"m{month_number}-w{task.week}-d{task.day:02d}",
                    parent_id=week_nodes[task.week].id,
                    ordinal=task.day,
                    kind="day",
                    title=task.source_heading,
                    source_path=task.source_path,
                    source_anchor=task.source_heading,
                )
                self._session.add(node)
                await self._session.flush()
                day_nodes[task.day] = node
            task_node = CurriculumNode(
                owner_id=owner_id,
                roadmap_version_id=version_id,
                stable_id=f"node:{task.stable_id}",
                parent_id=day_nodes[task.day].id,
                ordinal=task.order,
                kind="task",
                title=task.objective,
                source_path=task.source_path,
                source_anchor=task.source_heading,
            )
            self._session.add(task_node)
            await self._session.flush()
            definition = TaskDefinition(
                owner_id=owner_id,
                roadmap_version_id=version_id,
                curriculum_node_id=task_node.id,
                stable_id=task.stable_id,
                exercise_type=task.exercise_type,
                mapping_version=task.mapping_version,
                objective=task.objective,
                timebox_minutes=task.timebox_minutes,
                block=task.block,
                required=task.required,
                output_contract={
                    "schema_version": 1,
                    "items": list(task.required_output),
                    "procedure": [item.to_dict() for item in task.procedure],
                    "constraints": list(task.constraints),
                    "correction_selection": (
                        task.correction_selection.to_dict()
                        if task.correction_selection is not None
                        else None
                    ),
                },
                pass_contract={"schema_version": 1, "items": list(task.pass_criteria)},
                evidence_contract={
                    "schema_version": 1,
                    "items": list(task.evidence_requirements),
                },
                source_references=[
                    {"path": task.source_path, "heading": task.source_heading}
                ],
                allowed_ai_role=task.allowed_ai_role,
                source_path=task.source_path,
                source_anchor=task.source_heading,
            )
            self._session.add(definition)
            await self._session.flush()
            for ordinal, criterion in enumerate(task.pass_criteria):
                self._session.add(
                    PassCriterion(
                        owner_id=owner_id,
                        roadmap_version_id=version_id,
                        stable_id=f"{task.stable_id}:pass:{ordinal + 1}",
                        curriculum_node_id=None,
                        task_definition_id=definition.id,
                        description=criterion,
                        rubric={"schema_version": 1},
                        evidence={"schema_version": 1},
                        ordinal=ordinal,
                    )
                )
        for ordinal, resource in enumerate(parsed.resources):
            digest = hashlib.sha256(resource.key.encode()).hexdigest()[:24]
            self._session.add(
                Resource(
                    owner_id=owner_id,
                    roadmap_version_id=version_id,
                    stable_id=f"resource:{digest}",
                    curriculum_node_id=None,
                    task_definition_id=None,
                    kind=resource.kind,
                    title=resource.labels[0] if resource.labels else resource.key,
                    locator=resource.key,
                    required=True,
                    source_path=resource.source_paths[0] if resource.source_paths else None,
                    source_anchor=None,
                    ordinal=ordinal,
                )
            )
        for ordinal, exit_item in enumerate(parsed.exit_criteria):
            digest = hashlib.sha256(exit_item.text.encode()).hexdigest()[:24]
            self._session.add(
                ExitCriterion(
                    owner_id=owner_id,
                    roadmap_version_id=version_id,
                    stable_id=f"exit:{digest}",
                    month_number=month_number,
                    description=exit_item.text,
                    rubric={"schema_version": 1},
                    evidence={"schema_version": 1},
                    ordinal=ordinal,
                )
            )
        await self._session.flush()

    @staticmethod
    def _to_import(item: RoadmapImport, source_key: str) -> RoadmapImportRecord:
        return RoadmapImportRecord(
            id=item.id,
            owner_id=item.owner_id,
            source_id=item.source_id,
            source_key=source_key,
            package_hash=item.package_hash.hex(),
            object_key=item.object_key,
            status=item.status,
            validation_report=cast(dict[str, object], item.validation_report),
            semantic_diff=cast(dict[str, object], item.semantic_diff),
            idempotency_key=item.idempotency_key,
            failure_code=item.failure_code,
        )

    @staticmethod
    def _to_version(item: RoadmapVersion) -> RoadmapVersionRecord:
        return RoadmapVersionRecord(
            id=item.id,
            owner_id=item.owner_id,
            source_id=item.source_id,
            version_key=item.version_key,
            version_number=item.version_number,
            month_number=item.month_number,
            object_key=item.object_key,
            content_hash=item.content_hash.hex(),
            manifest=cast(dict[str, object], item.manifest),
            normalized_payload=cast(dict[str, object], item.normalized_payload),
            state=item.state,
            mirror_status=item.mirror_status,
            mirror_ref=item.mirror_ref,
            mirror_error_code=item.mirror_error_code,
        )
