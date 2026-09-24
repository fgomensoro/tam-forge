# ruff: noqa: E501
"""A later version's day 1 lands on the first date it can own, not on the first activation date."""

from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).parents[5]
TIMEZONE = "America/Montevideo"

FILES: dict[str, bytes] = {
    "Week 1.md": b"# Week 1\n\n## Day 1\n\nDo it.\n\n## Day 2\n\nAgain.\n\n## Day 3\n\nOnce more.\n",
}


def _day(day_id: str, heading: str, minutes: int) -> str:
    return f"""
  - id: {day_id}
    kind: weekday
    budget_minutes: {minutes}
    blocks:
      - {{id: {day_id}-learning, type: technical, minutes: {minutes - 15}, source: {{file: Week 1.md, heading: {heading}}}, objective: Read the day.}}
      - {{id: {day_id}-close, type: close, minutes: 15, source: {{file: Week 1.md, heading: {heading}}}, objective: Close the day.}}"""


# No rest weekdays, so every calendar date is a study date and the test does not
# depend on the weekday it runs on.
BASELINE = (
    "schema_version: 1\nprogram: {key: demo, title: Demo}\nrest_weekdays: []\ndays:"
    + _day("base-d01", "Day 1", 180)
    + _day("base-d02", "Day 2", 180)
    + _day("base-d03", "Day 3", 180)
    + "\n"
)
REFORECAST = (
    "schema_version: 1\nprogram: {key: demo-next, title: Demo}\nrest_weekdays: []\n"
    "lineage: {predecessor_version: demo}\ndays:"
    + _day("next-d01", "Day 2", 120)
    + _day("next-d02", "Day 3", 120)
    + "\n"
)


def _package(scheme: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(FILES):
            archive.writestr(name, FILES[name])
        archive.writestr("roadmap.yaml", scheme.encode("utf-8"))
    return buffer.getvalue()


@pytest.mark.integration
def test_reactivated_version_starts_on_the_first_unplanned_date(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.learning.models import ActivityInstance
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.roadmaps.models import RoadmapVersion
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore
    from tamforge_backend.today.repository import SqlAlchemyTodayRepository

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

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            try:
                async with factory() as session:
                    roadmaps = RoadmapService(
                        config=load_config_bundle(ROOT / "config"),
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=InMemoryObjectStore(),
                        mirror=None,
                    )

                    async def activate(scheme: str, key: str) -> int:
                        with inspect_zip_stream((_package(scheme),)) as package:
                            staged = await roadmaps.stage_package(
                                owner_id=owner_id,
                                source_key="obsidian-main",
                                source_name="Demo",
                                source_kind="obsidian",
                                package_kind="zip",
                                idempotency_key=key,
                                package=package,
                            )
                        assert staged.status == "validated", staged.validation_report
                        approved = await roadmaps.approve_import(
                            owner_id=owner_id, import_id=staged.id
                        )
                        await roadmaps.activate_version(
                            owner_id=owner_id, version_id=approved.id, timezone=TIMEZONE
                        )
                        return approved.id

                    now = datetime.now(UTC)
                    today = now.astimezone(ZoneInfo(TIMEZONE)).date()
                    tomorrow = today + timedelta(days=1)

                    baseline_id = await activate(BASELINE, "baseline")
                    days = StudyDayService(session)
                    first = await days.ensure_current_day(owner_id=owner_id, at=now)
                    assert first is not None and first.roadmap_version_id == baseline_id

                    # Reforecast mid-day: today is frozen under the baseline.
                    reforecast_id = await activate(REFORECAST, "reforecast")
                    async with session.begin():
                        anchor = await session.scalar(
                            select(RoadmapVersion.starts_on).where(
                                RoadmapVersion.id == reforecast_id
                            )
                        )
                    assert anchor == tomorrow

                    again = await days.ensure_current_day(owner_id=owner_id, at=now)
                    assert again is not None
                    assert (again.id, again.created) == (first.id, False)

                    next_day = await days.ensure_current_day(
                        owner_id=owner_id, at=now + timedelta(days=1)
                    )
                    assert next_day is not None and next_day.created
                    assert next_day.roadmap_version_id == reforecast_id
                    async with session.begin():
                        stable_ids = (
                            await session.scalars(
                                select(ActivityInstance.task_stable_id_snapshot)
                                .where(ActivityInstance.study_day_id == next_day.id)
                                .order_by(ActivityInstance.id)
                            )
                        ).all()
                    assert stable_ids == ["next-d01-learning", "next-d01-close"]

                today_view = await SqlAlchemyTodayRepository(factory()).load_today(
                    owner_id=owner_id, local_date=today
                )
                assert today_view.roadmap.version_id == baseline_id
                assert (today_view.roadmap.week, today_view.roadmap.day) == (1, 1)
                assert today_view.budget is not None
                assert today_view.budget.target_minutes == 180

                tomorrow_view = await SqlAlchemyTodayRepository(factory()).load_today(
                    owner_id=owner_id, local_date=tomorrow
                )
                assert tomorrow_view.roadmap.version_id == reforecast_id
                assert (tomorrow_view.roadmap.week, tomorrow_view.roadmap.day) == (1, 1)
                assert tomorrow_view.budget is not None
                assert tomorrow_view.budget.target_minutes == 120
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        with sync_engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        sync_engine.dispose()
