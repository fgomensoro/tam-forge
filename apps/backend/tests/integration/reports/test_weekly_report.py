"""A week's report is queued when due, composed from aggregates, stored, and read back."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
CONFIG_DIR = Path(__file__).parents[5] / "config"


class FakeReportTransport:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def weekly_report(self, request: object) -> Mapping[str, object]:
        self.requests.append(request)
        skills = request.skills  # type: ignore[attr-defined]
        return {
            "headline": "A quiet week on record.",
            "did": ["Nothing was closed."],
            "learned": ["The report runs even on an empty week."],
            "improved": ["Nothing measurable yet."],
            "skills": [
                {"skill_slug": s.slug, "direction": "flat", "note": "No events."} for s in skills
            ],
            "suggestions": [
                {
                    "change": "Start with one SQL block on Monday.",
                    "reason": "No evidence landed.",
                    "skill_slug": skills[0].slug,
                }
            ],
            "risks": ["The streak has not started."],
            "decision_for_frank": "Pick the first block of next week.",
        }


def test_weekly_report_round_trip(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.weekly_report import WeeklyReportService
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.evidence.seed import seed_config
    from tamforge_backend.reports.service import ReportConflict, ReportInvalid, WeeklyReportQueue
    from tamforge_backend.workers.claude import weekly_report_step

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
            connection.execute(
                text(
                    "INSERT INTO learner_settings (owner_id, timezone, study_start_date) "
                    "VALUES (:owner, 'America/Los_Angeles', '2026-08-24')"
                ),
                {"owner": owner_id},
            )

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            transport = FakeReportTransport()
            analyst = WeeklyReportService(transport, model="claude-fable-5-1")
            # Tuesday 2026-09-15 17:30 in Los Angeles: the week of 2026-09-07 is the one due.
            # The moment sits in the past so the queue's available_at is claimable now.
            now = datetime(2026, 9, 16, 0, 30, tzinfo=UTC)
            try:
                async with factory() as session:
                    queue = WeeklyReportQueue(session, analyst=analyst, clock=lambda: now)
                    with pytest.raises(ReportInvalid):
                        await queue.request(owner_id=owner_id, week_start=date(2026, 9, 8))
                    with pytest.raises(ReportInvalid):
                        await queue.request(owner_id=owner_id, week_start=date(2026, 9, 14))
                    assert await queue.schedule_due(now=now) == 1
                    assert await queue.schedule_due(now=now) == 0  # the key holds
                    pending = await queue.read(owner_id=owner_id, week_start=date(2026, 9, 7))
                    assert pending.status == "queued"
                # Without the skill catalog the job parks as invalid input.
                assert await weekly_report_step(factory, analyst=analyst, now=now) == 0
                async with factory() as session:
                    queue = WeeklyReportQueue(session, analyst=analyst, clock=lambda: now)
                    parked = await queue.read(owner_id=owner_id, week_start=date(2026, 9, 7))
                    assert parked.status == "needs_attention"
                    assert parked.failure_category == "invalid_input"
                    async with transaction_scope(session):
                        await seed_config(
                            load_config_bundle(CONFIG_DIR),
                            owner_id=owner_id,
                            session=session,
                            apply=True,
                        )
                    await queue.process(owner_id=owner_id, week_start=date(2026, 9, 7))
                async with factory() as session:
                    queue = WeeklyReportQueue(session, analyst=analyst, clock=lambda: now)
                    ready = await queue.read(owner_id=owner_id, week_start=date(2026, 9, 7))
                    assert ready.status == "ready", ready
                    assert ready.week_end == date(2026, 9, 13)
                    assert ready.delivery_status == "skipped"
                    assert "no delivery channel" in (ready.delivery_detail or "")
                    assert len(ready.skills) == 14
                    assert ready.skills[0].skill_name
                    assert ready.suggestions and ready.decision_for_frank
                    listed = await queue.list(owner_id=owner_id)
                    assert [r.week_start for r in listed.items] == [date(2026, 9, 7)]
                    with pytest.raises(ReportConflict):
                        await queue.request(owner_id=owner_id, week_start=date(2026, 9, 7))
                    request = transport.requests[-1]
                    assert request.aggregates["study_days"] == 0  # type: ignore[attr-defined]
                    assert request.coverage is None  # type: ignore[attr-defined]
                    assert len(request.skills) == 14  # type: ignore[attr-defined]
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
