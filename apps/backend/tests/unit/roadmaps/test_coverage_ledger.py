"""The coverage ledger and interview queue derive their statuses from what happened."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.coverage_ledger.routes import get_coverage_service
from tamforge_backend.coverage_ledger.schemas import (
    CoverageItem,
    CoverageLedgerResponse,
    InterviewQueueItem,
)
from tamforge_backend.coverage_ledger.service import (
    ActivityFacts,
    CoverageNotFound,
    coverage_status,
    evidence_status,
    queue_status,
    summarize,
)
from tamforge_backend.main import create_app

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


def _facts(**overrides: object) -> ActivityFacts:
    values: dict[str, object] = {
        "activity_ids": (1,),
        "states": ("ready",),
        "committed": False,
        "counted_seconds": 0,
        "evidence_event_ids": (),
        "qualifying": False,
        "real_interview_attempts": 0,
        "last_activity_at": None,
    }
    values.update(overrides)
    return ActivityFacts(**values)  # type: ignore[arg-type]


def test_coverage_statuses_are_the_ones_frank_keeps_by_hand() -> None:
    assert coverage_status(_facts(activity_ids=(), states=())) == "pending"
    assert coverage_status(_facts(states=("ready",))) == "pending"
    assert coverage_status(_facts(states=("active",))) == "in_progress"
    assert coverage_status(_facts(states=("output_committed",), committed=True)) == "in_progress"
    assert coverage_status(_facts(states=("feedback_ready",))) == "not_assessed"
    assert (
        coverage_status(_facts(states=("feedback_ready",), evidence_event_ids=(9,))) == "completed"
    )
    assert (
        coverage_status(_facts(states=("skipped", "completed"), evidence_event_ids=(9,)))
        == "completed"
    )


def test_evidence_and_queue_statuses_follow_the_ledger_and_the_attempts() -> None:
    assert evidence_status(_facts()) == "none"
    assert evidence_status(_facts(evidence_event_ids=(1,))) == "nonqualifying"
    assert evidence_status(_facts(evidence_event_ids=(1,), qualifying=True)) == "qualifying"
    assert queue_status(_facts()) == "pending"
    assert queue_status(_facts(states=("active",))) == "in_progress"
    assert queue_status(_facts(states=("output_committed",), committed=True)) == "practiced"
    assert queue_status(_facts(real_interview_attempts=1)) == "practiced"
    assert queue_status(_facts(committed=True, evidence_event_ids=(3,))) == "assessed"


def _item(stable_id: str, status: str, planned: int = 30, actual: int = 0) -> CoverageItem:
    return CoverageItem(
        task_definition_id=hash(stable_id) % 1000,
        stable_id=stable_id,
        title="Day",
        block="sql",
        objective="Do the thing.",
        exercise_type="sql_guided_lesson",
        status=status,  # type: ignore[arg-type]
        evidence_status="none",
        planned_minutes=planned,
        actual_minutes=actual,
        activity_ids=(),
        evidence_event_ids=(),
        last_activity_at=None,
    )


def _queue(position: int, status: str) -> InterviewQueueItem:
    return InterviewQueueItem(
        position=position,
        task_definition_id=position,
        stable_id=f"q{position}",
        question=f"Question {position}?",
        status=status,  # type: ignore[arg-type]
        activity_ids=(),
        real_interview_attempts=0,
        evidence_event_ids=(),
    )


def test_summary_counts_statuses_minutes_and_names_the_next_question() -> None:
    items = [
        _item("a", "completed", 30, 28),
        _item("b", "pending"),
        _item("c", "not_assessed", 20, 25),
    ]
    queue = [
        _queue(1, "assessed"),
        _queue(2, "practiced"),
        _queue(3, "pending"),
        _queue(4, "pending"),
    ]
    summary = summarize(items, queue)
    assert (summary.required_items, summary.completed, summary.pending, summary.not_assessed) == (
        3,
        1,
        1,
        1,
    )
    assert (summary.planned_minutes, summary.actual_minutes) == (80, 53)
    assert (summary.queue_items, summary.queue_practiced) == (4, 2)
    assert summary.next_question == "Question 3?"
    assert summarize([], []).next_question is None


class StubService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int | None]] = []
        self.error: Exception | None = None

    async def read(self, *, owner_id: int, version_id: int | None = None) -> CoverageLedgerResponse:
        self.calls.append((owner_id, version_id))
        if self.error is not None:
            raise self.error
        items = (_item("m1-w1-d01-sql", "completed"),)
        queue = (_queue(1, "pending"),)
        return CoverageLedgerResponse(
            roadmap_version_id=version_id or 8,
            version_key="month-1-v2",
            summary=summarize(items, queue),
            items=items,
            interview_queue=queue,
        )


def _client() -> tuple[TestClient, StubService]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubService()
    app.dependency_overrides[get_coverage_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    return TestClient(app), service


def test_coverage_routes_read_the_active_or_a_named_version() -> None:
    client, service = _client()
    with client:
        active = client.get("/api/v1/coverage")
        named = client.get("/api/v1/roadmap-versions/12/coverage")
        service.error = CoverageNotFound("internal")
        missing = client.get("/api/v1/coverage")

    assert active.status_code == 200, active.text
    assert active.headers["cache-control"] == "no-store"
    assert active.json()["summary"]["required_items"] == 1
    assert active.json()["interview_queue"][0]["question"] == "Question 1?"
    assert named.status_code == 200 and named.json()["roadmap_version_id"] == 12
    assert service.calls[:2] == [(1, None), (1, 12)]
    assert missing.status_code == 404 and missing.json()["code"] == "coverage_not_found"
    assert "internal" not in missing.text
