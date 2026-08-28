from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"


def test_study_day_creation_is_timezone_aware_idempotent_and_snapshot_bound(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.learning.models import ActivityInstance, LearnerSetting, StudyDay
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore
    from tamforge_backend.today.models import Interview

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
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
                    roadmap_service = RoadmapService(
                        config=load_config_bundle(ROOT / "config"),
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=InMemoryObjectStore(),
                        mirror=None,
                    )
                    with inspect_zip_stream((FIXTURE.read_bytes(),)) as package:
                        staged = await roadmap_service.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="study-day-roadmap",
                            package=package,
                        )
                    approved = await roadmap_service.approve_import(
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
                    await roadmap_service.activate_version(
                        owner_id=owner_id,
                        version_id=approved.id,
                    )
                    async with transaction_scope(session):
                        session.add(
                            Interview(
                                owner_id=owner_id,
                                company="ExampleCo",
                                role="Technical Account Manager",
                                stage="Hiring manager",
                                starts_at=datetime(2026, 8, 25, 19, tzinfo=UTC),
                                expected_duration_minutes=60,
                                status="scheduled",
                                privacy_permission_code="permission_not_requested",
                            )
                        )

                    day_service = StudyDayService(session)
                    first = await day_service.ensure_current_day(
                        owner_id=owner_id,
                        at=datetime(2026, 8, 24, 19, tzinfo=UTC),
                    )
                    repeated = await day_service.ensure_current_day(
                        owner_id=owner_id,
                        at=datetime(2026, 8, 24, 23, tzinfo=UTC),
                    )
                    interview_day = await day_service.ensure_current_day(
                        owner_id=owner_id,
                        at=datetime(2026, 8, 25, 20, tzinfo=UTC),
                    )
                    sunday = await day_service.ensure_current_day(
                        owner_id=owner_id,
                        at=datetime(2026, 8, 30, 19, tzinfo=UTC),
                    )

                    assert first is not None
                    assert repeated is not None
                    assert first.created
                    assert not repeated.created
                    assert first.id == repeated.id
                    assert first.local_date == date(2026, 8, 24)
                    assert first.planned_minutes == 240
                    assert first.roadmap_version_id == approved.id
                    assert len(first.activity_ids) == 7
                    assert first.activity_ids == repeated.activity_ids
                    assert interview_day is not None
                    assert interview_day.day_type == "interview"
                    assert interview_day.planned_minutes == 205
                    assert len(interview_day.activity_ids) == 5
                    assert sunday is None
                    assert (
                        await session.scalar(select(func.count()).select_from(StudyDay))
                    ) == 2
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(ActivityInstance)
                        )
                    ) == 12
                    snapshots = tuple(
                        (
                            await session.execute(
                                select(
                                    ActivityInstance.task_stable_id_snapshot,
                                    ActivityInstance.task_mapping_version_snapshot,
                                    ActivityInstance.task_timebox_minutes_snapshot,
                                    ActivityInstance.roadmap_version_key_snapshot,
                                )
                                .where(ActivityInstance.study_day_id == first.id)
                                .order_by(ActivityInstance.id)
                            )
                        ).all()
                    )
                    assert all(item[0].startswith("m1-w1-d01-") for item in snapshots)
                    assert all(item[1] for item in snapshots)
                    assert sum(item[2] for item in snapshots) == 240
                    assert {item[3] for item in snapshots} == {approved.version_key}
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
