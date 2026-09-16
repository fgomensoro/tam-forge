"""The weekly report step queues the due week, then composes one; failures close."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest
from tamforge_backend.agents.roles.weekly_report import WeeklyReportService
from tamforge_backend.jobs.schemas import EnqueueJobCommand, ReferencePayload
from tamforge_backend.jobs.service import JobService
from tamforge_backend.reports.service import ReportInvalid, ReportsUnavailable
from tamforge_backend.testing.jobs import FakeJobStore
from tamforge_backend.workers import claude as claude_worker

NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
WEEK = date(2026, 9, 7)


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _queue(store: FakeJobStore) -> int:
    result = asyncio.run(
        JobService(store).enqueue(
            owner_id=1,
            command=EnqueueJobCommand(
                kind="claude_weekly_report",
                payload=ReferencePayload(subject_id=WEEK.toordinal()),
                priority=40,
                available_at=NOW,
            ),
            idempotency_key=f"claude-weekly-report-o1-{WEEK.isoformat()}",
        )
    )
    return result.job.id


def _run(monkeypatch: pytest.MonkeyPatch, store: FakeJobStore, process) -> tuple[int, list[object]]:  # type: ignore[no-untyped-def]
    scheduled: list[object] = []

    class Queue:
        def __init__(self, session: object, *, analyst: object, sender: object = None) -> None:
            pass

        async def schedule_due(self, *, now: object = None, limit: int = 20) -> int:
            scheduled.append(now)
            return 0

        async def process(self, *, owner_id: int, week_start: date) -> object:
            return process(week_start)

    class Repo:
        def __init__(self, session: object) -> None:
            pass

    import tamforge_backend.jobs.repository as jobs_repository
    import tamforge_backend.jobs.service as jobs_service
    import tamforge_backend.reports.service as reports_module

    monkeypatch.setattr(reports_module, "WeeklyReportQueue", Queue)
    monkeypatch.setattr(jobs_repository, "SqlAlchemyJobRepository", Repo)
    monkeypatch.setattr(jobs_service, "JobService", lambda repository: JobService(store))
    analyst = WeeklyReportService(None, model="m")
    processed = asyncio.run(
        claude_worker.weekly_report_step(lambda: _Session(), analyst=analyst, now=NOW)  # type: ignore[arg-type]
    )
    return processed, scheduled


def test_a_composed_report_completes_its_job_after_scheduling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeJobStore(now=NOW)
    job_id = _queue(store)
    seen: list[date] = []
    processed, scheduled = _run(monkeypatch, store, lambda week: seen.append(week))
    assert processed == 1 and seen == [WEEK] and scheduled == [NOW]
    assert store.jobs[job_id].state == "succeeded"


def test_failures_park_or_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeJobStore(now=NOW)
    invalid_job = _queue(store)

    def invalid(week: date) -> object:
        raise ReportInvalid("no catalog")

    assert _run(monkeypatch, store, invalid)[0] == 0
    assert store.jobs[invalid_job].state == "failed"
    assert store.jobs[invalid_job].last_error_category == "invalid_input"

    store = FakeJobStore(now=NOW)
    down_job = _queue(store)

    def down(week: date) -> object:
        raise ReportsUnavailable("the subscription quota is spent")

    _run(monkeypatch, store, down)
    assert store.jobs[down_job].last_error_category == "resource_exhausted"
    assert store.jobs[down_job].state == "queued"
