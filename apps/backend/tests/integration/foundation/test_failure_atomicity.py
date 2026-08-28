"""Failure injection for the foundation's irreversible evidence boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
V1 = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"
V2 = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v2.zip"


def test_orphaned_snapshot_is_reconciled_and_mirror_failure_preserves_active_version(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.roadmaps.models import RoadmapImport, RoadmapVersion
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.ports import MirrorFailure, MirrorRequest
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore

    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(migration, "base")
        command.upgrade(migration, "head")
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            store = InMemoryObjectStore()
            bundle = load_config_bundle(ROOT / "config")

            class FailingCreateRepository(SqlAlchemyRoadmapRepository):
                async def create_staged_import(self, **kwargs):  # type: ignore[no-untyped-def]
                    raise RuntimeError("forced failure before database commit")

            class SwitchableMirror:
                enabled = True

                def __init__(self) -> None:
                    self.fail = True
                    self.calls = 0

                async def mirror(self, request: MirrorRequest) -> str:
                    del request
                    self.calls += 1
                    if self.fail:
                        raise MirrorFailure("storage_unavailable")
                    return "b" * 40

            try:
                async with factory() as session:
                    failing = RoadmapService(
                        config=bundle,
                        repository=FailingCreateRepository(session),
                        object_store=store,
                        mirror=None,
                    )
                    with inspect_zip_stream((V1.read_bytes(),)) as package:
                        with pytest.raises(
                            RuntimeError,
                            match="forced failure before database commit",
                        ):
                            await failing.stage_package(
                                owner_id=owner_id,
                                source_key="obsidian-main",
                                source_name="TAM Roadmap",
                                source_kind="obsidian",
                                package_kind="zip",
                                idempotency_key="atomic-stage",
                                package=package,
                            )

                async with factory() as session:
                    assert await session.scalar(
                        select(func.count()).select_from(RoadmapImport)
                    ) == 0

                async with factory() as session:
                    service = RoadmapService(
                        config=bundle,
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=store,
                        mirror=None,
                    )
                    with inspect_zip_stream((V1.read_bytes(),)) as package:
                        recovered = await service.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="atomic-stage",
                            package=package,
                        )
                    with inspect_zip_stream((V1.read_bytes(),)) as package:
                        duplicate = await service.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="atomic-stage-retry",
                            package=package,
                        )
                    assert duplicate.id == recovered.id
                    stored = await store.stat(recovered.object_key)
                    assert stored is not None
                    baseline = await service.approve_import(
                        owner_id=owner_id,
                        import_id=recovered.id,
                    )
                    baseline = await service.activate_version(
                        owner_id=owner_id,
                        version_id=baseline.id,
                    )
                    assert baseline.state == "active"

                mirror = SwitchableMirror()
                async with factory() as session:
                    service = RoadmapService(
                        config=replace(bundle, roadmap_version="month-1-v3"),
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=store,
                        mirror=mirror,
                    )
                    with inspect_zip_stream((V2.read_bytes(),)) as package:
                        candidate_import = await service.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="atomic-mirror",
                            package=package,
                        )
                    candidate = await service.approve_import(
                        owner_id=owner_id,
                        import_id=candidate_import.id,
                    )
                    assert candidate.state == "approved"
                    assert candidate.mirror_status == "failed"
                    assert candidate.mirror_error_code == "storage_unavailable"

                async with factory() as session:
                    active = await session.scalar(
                        select(RoadmapVersion).where(RoadmapVersion.state == "active")
                    )
                    assert active is not None
                    assert active.id == baseline.id
                    assert await session.scalar(
                        select(func.count()).select_from(RoadmapImport)
                    ) == 2

                mirror.fail = False
                async with factory() as session:
                    service = RoadmapService(
                        config=bundle,
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=store,
                        mirror=mirror,
                    )
                    mirrored = await service.retry_mirror(
                        owner_id=owner_id,
                        version_id=candidate.id,
                    )
                    assert mirrored.mirror_status == "synced"
                    assert mirrored.mirror_ref == "b" * 40
                    activated = await service.activate_version(
                        owner_id=owner_id,
                        version_id=candidate.id,
                    )
                    assert activated.state == "active"
                    assert mirror.calls == 2
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()


def test_output_commit_failure_rolls_back_before_idempotent_retry(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, event, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.learning.models import ActivityInstance, Attempt, LearnerSetting
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.learning.service import ActivityService
    from tamforge_backend.roadmaps.models import TaskDefinition
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore

    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(migration, "base")
        command.upgrade(migration, "head")
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()
        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")

        async def exercise() -> None:
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            try:
                async with factory() as session:
                    roadmap = RoadmapService(
                        config=load_config_bundle(ROOT / "config"),
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=InMemoryObjectStore(),
                        mirror=None,
                    )
                    with inspect_zip_stream((V1.read_bytes(),)) as package:
                        staged = await roadmap.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="output-roadmap",
                            package=package,
                        )
                    approved = await roadmap.approve_import(
                        owner_id=owner_id,
                        import_id=staged.id,
                    )
                    async with transaction_scope(session):
                        session.add(
                            LearnerSetting(
                                owner_id=owner_id,
                                timezone="America/Los_Angeles",
                                study_start_date=date(2026, 8, 24),
                                active_roadmap_version_id=None,
                            )
                        )
                    active = await roadmap.activate_version(
                        owner_id=owner_id,
                        version_id=approved.id,
                    )
                    day = await StudyDayService(session).ensure_current_day(
                        owner_id=owner_id,
                        at=datetime(2026, 8, 24, 19, tzinfo=UTC),
                    )
                    assert day is not None
                    activity_id = (
                        await session.execute(
                            select(ActivityInstance.id)
                            .join(
                                TaskDefinition,
                                TaskDefinition.id == ActivityInstance.task_definition_id,
                            )
                            .where(ActivityInstance.owner_id == owner_id)
                            .where(ActivityInstance.study_day_id == day.id)
                            .where(TaskDefinition.block == "technical_learning")
                        )
                    ).scalar_one()
                    await session.rollback()
                    activity = ActivityService(session)
                    started = await activity.start(
                        owner_id=owner_id,
                        activity_id=activity_id,
                        expected_version=1,
                        idempotency_key="output-start",
                    )
                    hidden = await activity.set_source_visibility(
                        owner_id=owner_id,
                        activity_id=activity_id,
                        expected_version=started.optimistic_version,
                        hidden=True,
                        idempotency_key="output-hide",
                    )
                    expected_version = hidden.optimistic_version

                output = {
                    "contract_version": 1,
                    "kind": "reading",
                    "prompt": (
                        "Read A1–A3; produce a request/response map and error matrix "
                        "for the assigned HTTP status codes."
                    ),
                    "audience": "Technical hiring manager",
                    "time_limit_minutes": 45,
                    "key_ideas": ["Methods matter.", "Status classes matter.", "Impact matters."],
                    "boundary_or_failure": "Transport success can hide a business failure.",
                    "tam_customer_example": "Check order state before retrying.",
                    "unresolved_question": "Which errors use a successful status?",
                }

                async with factory() as session:
                    def fail_when_attempt_is_flushed(
                        sync_session,  # type: ignore[no-untyped-def]
                        flush_context,  # type: ignore[no-untyped-def]
                        instances,  # type: ignore[no-untyped-def]
                    ) -> None:
                        del flush_context, instances
                        if any(isinstance(item, Attempt) for item in sync_session.new):
                            raise RuntimeError("forced output persistence failure")

                    event.listen(session.sync_session, "before_flush", fail_when_attempt_is_flushed)
                    try:
                        with pytest.raises(
                            RuntimeError,
                            match="forced output persistence failure",
                        ):
                            await ActivityService(session).commit_output(
                                owner_id=owner_id,
                                activity_id=activity_id,
                                expected_version=expected_version,
                                client_sequence=1,
                                output=output,
                                artifact_refs=(),
                                parent_attempt_id=None,
                                idempotency_key="output-commit",
                            )
                    finally:
                        event.remove(
                            session.sync_session,
                            "before_flush",
                            fail_when_attempt_is_flushed,
                        )

                async with factory() as session:
                    unchanged = await session.get(ActivityInstance, activity_id)
                    assert unchanged is not None
                    assert unchanged.state == "active"
                    assert unchanged.optimistic_version == expected_version
                    assert await session.scalar(
                        select(func.count()).select_from(Attempt)
                    ) == 0
                    await session.rollback()
                    committed = await ActivityService(session).commit_output(
                        owner_id=owner_id,
                        activity_id=activity_id,
                        expected_version=expected_version,
                        client_sequence=1,
                        output=output,
                        artifact_refs=(),
                        parent_attempt_id=None,
                        idempotency_key="output-commit",
                    )
                    replayed = await ActivityService(session).commit_output(
                        owner_id=owner_id,
                        activity_id=activity_id,
                        expected_version=expected_version,
                        client_sequence=1,
                        output=output,
                        artifact_refs=(),
                        parent_attempt_id=None,
                        idempotency_key="output-commit",
                    )
                    assert replayed == committed
                    assert active.state == "active"
                async with factory() as session:
                    assert await session.scalar(
                        select(func.count()).select_from(Attempt)
                    ) == 1
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()


def test_snapshot_recalculation_failure_keeps_prior_evidence_and_retries_once(
    test_database_url: str,
) -> None:
    from sqlalchemy import func, select
    from tamforge_backend.evidence.models import (
        RubricEvaluation,
        SkillEvidenceEvent,
        SkillSnapshot,
    )
    from tamforge_backend.evidence.repository import SqlAlchemyEvidenceRepository
    from tamforge_backend.evidence.service import EvidenceService

    from apps.backend.tests.integration.evidence._helpers import (
        evaluation_command,
        seed_evidence_case,
    )

    class FailingSnapshotRepository(SqlAlchemyEvidenceRepository):
        async def _save_snapshot(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            raise RuntimeError("forced snapshot recalculation failure")

    async def exercise() -> None:
        case = await seed_evidence_case(test_database_url)
        try:
            first_command = evaluation_command(case)
            async with case.session_factory() as session:
                first = await EvidenceService(
                    SqlAlchemyEvidenceRepository(session)
                ).record(
                    owner_id=case.owner_id,
                    command=first_command,
                    idempotency_key="atomic-evidence-first",
                )
            async with case.session_factory() as session:
                baseline_snapshots = tuple(
                    (
                        await session.scalars(
                            select(SkillSnapshot).order_by(SkillSnapshot.id)
                        )
                    ).all()
                )
                baseline_values = tuple(
                    (item.id, item.estimated_level, item.contributing_event_manifest)
                    for item in baseline_snapshots
                )
                baseline_events = await session.scalar(
                    select(func.count()).select_from(SkillEvidenceEvent)
                )
                baseline_evaluations = await session.scalar(
                    select(func.count()).select_from(RubricEvaluation)
                )

            retry_command = first_command.model_copy(
                update={"evaluated_at": datetime.now(UTC)}
            )
            async with case.session_factory() as session:
                with pytest.raises(
                    RuntimeError,
                    match="forced snapshot recalculation failure",
                ):
                    await EvidenceService(FailingSnapshotRepository(session)).record(
                        owner_id=case.owner_id,
                        command=retry_command,
                        idempotency_key="atomic-evidence-retry",
                    )
            async with case.session_factory() as session:
                assert await session.scalar(
                    select(func.count()).select_from(SkillEvidenceEvent)
                ) == baseline_events
                assert await session.scalar(
                    select(func.count()).select_from(RubricEvaluation)
                ) == baseline_evaluations
                unchanged = tuple(
                    (
                        item.id,
                        item.estimated_level,
                        item.contributing_event_manifest,
                    )
                    for item in (
                        await session.scalars(
                            select(SkillSnapshot).order_by(SkillSnapshot.id)
                        )
                    ).all()
                )
                assert unchanged == baseline_values

            async with case.session_factory() as session:
                service = EvidenceService(SqlAlchemyEvidenceRepository(session))
                retried = await service.record(
                    owner_id=case.owner_id,
                    command=retry_command,
                    idempotency_key="atomic-evidence-retry",
                )
            async with case.session_factory() as session:
                replayed = await EvidenceService(
                    SqlAlchemyEvidenceRepository(session)
                ).record(
                    owner_id=case.owner_id,
                    command=retry_command,
                    idempotency_key="atomic-evidence-retry",
                )
                assert replayed == retried
                assert set(first.evidence_event_ids).isdisjoint(retried.evidence_event_ids)
                assert await session.scalar(
                    select(func.count()).select_from(RubricEvaluation)
                ) == baseline_evaluations + 1
        finally:
            await case.engine.dispose()

    asyncio.run(exercise())
