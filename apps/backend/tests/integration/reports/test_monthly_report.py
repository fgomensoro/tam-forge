"""A month's report is queued when due, composed against the targets, stored, and read back."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
CONFIG_DIR = Path(__file__).parents[5] / "config"


class FakeMonthlyTransport:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def monthly_report(self, request: object) -> Mapping[str, object]:
        self.requests.append(request)
        skills = request.skills  # type: ignore[attr-defined]
        ranked = [
            s.slug
            for s in sorted(skills, key=lambda s: (-s.gap_to_month_one, s.slug))
            if s.gap_to_month_one > 0
        ][:5]
        return {
            "headline": "No evidence yet; every skill sits at its baseline.",
            "trajectory": [
                {"skill_slug": s.slug, "status": "no_evidence", "note": "No events."}
                for s in skills
            ],
            "largest_gaps": ranked,
            "coverage_verdict": "No roadmap version is active.",
            "exit_criteria_verdict": "Not assessable yet.",
            "best_evidence": [],
            "recommendation": "keep",
            "recommendation_reasoning": "Nothing has been measured; start the plan as written.",
            "next_month_priorities": ["Close the first study week."],
        }


def test_monthly_report_round_trip(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.monthly_report import MonthlyReportService
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.evidence.seed import seed_config
    from tamforge_backend.reports.monthly import MonthlyReportQueue
    from tamforge_backend.reports.service import ReportConflict, ReportInvalid
    from tamforge_backend.workers.claude import monthly_report_step

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
            transport = FakeMonthlyTransport()
            analyst = MonthlyReportService(transport, model="claude-fable-5-1")
            # 2026-09-15 17:30 in Los Angeles, in the past so the queue is claimable: August is due.
            now = datetime(2026, 9, 16, 0, 30, tzinfo=UTC)
            try:
                async with factory() as session:
                    queue = MonthlyReportQueue(session, analyst=analyst, clock=lambda: now)
                    with pytest.raises(ReportInvalid):
                        await queue.request(owner_id=owner_id, month_start=date(2026, 8, 2))
                    with pytest.raises(ReportInvalid):
                        await queue.request(owner_id=owner_id, month_start=date(2026, 9, 1))
                    assert await queue.schedule_due(now=now) == 1
                    assert await queue.schedule_due(now=now) == 0
                    pending = await queue.read(owner_id=owner_id, month_start=date(2026, 8, 1))
                    assert pending.status == "queued" and pending.month_end == date(2026, 8, 31)
                    async with transaction_scope(session):
                        await seed_config(
                            load_config_bundle(CONFIG_DIR),
                            owner_id=owner_id,
                            session=session,
                            apply=True,
                        )
                assert await monthly_report_step(factory, analyst=analyst, now=now) == 1
                async with factory() as session:
                    queue = MonthlyReportQueue(session, analyst=analyst, clock=lambda: now)
                    ready = await queue.read(owner_id=owner_id, month_start=date(2026, 8, 1))
                    assert ready.status == "ready", ready
                    assert ready.delivery_status == "skipped"
                    assert len(ready.trajectory) == 14
                    # Largest gap to the month-one target first, from the configured targets.
                    gaps = [t.gap_to_month_one for t in ready.trajectory]
                    assert gaps == sorted(gaps, reverse=True)
                    assert ready.largest_gaps[0] == ready.trajectory[0].skill_slug
                    assert ready.trajectory[0].skill_name
                    assert ready.recommendation == "keep"
                    listed = await queue.list(owner_id=owner_id)
                    assert [r.month_start for r in listed.items] == [date(2026, 8, 1)]
                    with pytest.raises(ReportConflict):
                        await queue.request(owner_id=owner_id, month_start=date(2026, 8, 1))
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
