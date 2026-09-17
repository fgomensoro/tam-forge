"""The weekly report role, its due-week rule, its text rendering, and its routes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.agents.roles.weekly_report import (
    WeeklyReportRequest,
    WeeklySkillInput,
    render_weekly_report_prompt,
    validate_weekly_report,
)
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.reports.delivery import NullReportSender, render_report_text
from tamforge_backend.reports.routes import get_weekly_report_queue
from tamforge_backend.reports.schemas import WeeklyReportPage, WeeklyReportResponse
from tamforge_backend.reports.service import ReportConflict, ReportInvalid, due_week, week_start_of

SKILLS = (
    WeeklySkillInput("sql_reconciliation", "SQL reconciliation", "2", "2.5", 3),
    WeeklySkillInput("tam_english", "TAM English", "2", "2", 1),
)
OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "headline": "SQL moved, English flat.",
        "did": ["Closed four days."],
        "learned": ["Idempotency keys."],
        "improved": ["SQL up half a point."],
        "skills": [
            {"skill_slug": "sql_reconciliation", "direction": "up", "note": "Three events."},
            {"skill_slug": "tam_english", "direction": "flat", "note": "One class."},
        ],
        "suggestions": [
            {
                "change": "Explain one query aloud.",
                "reason": "No English evidence.",
                "skill_slug": "tam_english",
            }
        ],
        "risks": [],
        "decision_for_frank": "Approve the spoken block.",
    }
    base.update(overrides)
    return base


def test_the_report_names_every_skill_once_and_never_applies_a_change() -> None:
    assert validate_weekly_report(_payload(), skills=SKILLS) == ()
    missing = _payload(skills=[_payload()["skills"][0]])  # type: ignore[index]
    assert "every skill exactly once" in validate_weekly_report(missing, skills=SKILLS)[0]
    outside = _payload(suggestions=[{"change": "x", "reason": "y", "skill_slug": "charisma"}])
    assert "catalog" in validate_weekly_report(outside, skills=SKILLS)[0]
    applied = _payload(decision_for_frank="None: I applied the change already.")
    assert "never applies" in validate_weekly_report(applied, skills=SKILLS)[0]
    shape = _payload(did=[])
    assert validate_weekly_report(shape, skills=SKILLS)[0].startswith("report ")


def test_the_prompt_carries_aggregates_skills_and_the_no_apply_rule() -> None:
    prompt = render_weekly_report_prompt(
        WeeklyReportRequest(
            week_start=date(2026, 9, 7),
            week_end=date(2026, 9, 13),
            skills=SKILLS,
            aggregates={"focused_minutes": 640},
            assessments=("2026-09-12: 1/4 contracts scored, average 3.00",),
            interviews=("2026-09-10 Coframe (screen, completed); not debriefed",),
            classes=("2026-09-11 with Maria: fluency 2.5, vocabulary 2.0, first_class",),
            coverage={"completed": 3, "pending": 20},
            repair_errors=("the report lists every skill exactly once",),
        )
    )
    assert "Week 2026-09-07 to 2026-09-13." in prompt
    assert "- focused_minutes: 640" in prompt
    assert "- sql_reconciliation: SQL reconciliation; 2 -> 2.5; 3 events" in prompt
    assert "Saturday assessment:" in prompt and "Real interviews:" in prompt
    assert "English classes:" in prompt and "Coverage ledger:" in prompt
    assert "Never apply a change" in prompt and "fix these:" in prompt


def test_the_due_week_turns_over_on_sunday_evening_local_time() -> None:
    # Sunday 2026-09-13 17:59 in Los Angeles: the week that ends today is not due yet.
    early = datetime(2026, 9, 14, 0, 59, tzinfo=UTC)
    assert due_week(early, "America/Los_Angeles") == date(2026, 8, 31)
    late = datetime(2026, 9, 14, 1, 0, tzinfo=UTC)  # 18:00 Sunday in Los Angeles
    assert due_week(late, "America/Los_Angeles") == date(2026, 9, 7)
    assert due_week(datetime(2026, 9, 16, 12, tzinfo=UTC), "UTC") == date(2026, 9, 7)
    assert week_start_of(date(2026, 9, 16)) == date(2026, 9, 14)


def test_no_week_is_due_that_ended_before_the_study_started() -> None:
    # Thursday 2026-09-17: the week of 2026-09-07 is due, and it ended on 2026-09-13.
    now = datetime(2026, 9, 17, 12, tzinfo=UTC)
    assert due_week(now, "UTC", study_start=date(2026, 9, 14)) is None
    assert due_week(now, "UTC", study_start=date(2026, 9, 13)) == date(2026, 9, 7)


def test_the_text_rendering_and_the_null_sender() -> None:
    import asyncio

    text = render_report_text("2026-09-07", "2026-09-13", _payload())
    assert text.startswith("TAM Forge weekly report, 2026-09-07 to 2026-09-13")
    assert "- sql_reconciliation: up; Three events." in text
    assert "Suggested adjustments (nothing is applied until you approve it):" in text
    assert text.endswith("Decision for you this week: Approve the spoken block.")
    delivery = asyncio.run(NullReportSender().send(owner_id=1, subject="s", body="b"))
    assert delivery.status == "skipped" and "no delivery channel" in delivery.detail


class StubQueue:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.requested: list[date | None] = []

    async def list(self, *, owner_id: int, limit: int = 12) -> WeeklyReportPage:
        return WeeklyReportPage(items=(self._ready(),))

    async def request(self, *, owner_id: int, week_start: date | None) -> WeeklyReportResponse:
        if self.error is not None:
            raise self.error
        self.requested.append(week_start)
        return WeeklyReportResponse(
            week_start=week_start or date(2026, 9, 7), week_end=date(2026, 9, 13), status="queued"
        )

    async def read(self, *, owner_id: int, week_start: date) -> WeeklyReportResponse:
        return self._ready()

    @staticmethod
    def _ready() -> WeeklyReportResponse:
        return WeeklyReportResponse(
            week_start=date(2026, 9, 7),
            week_end=date(2026, 9, 13),
            status="ready",
            report_id=1,
            model="claude-fable-5-1",
            delivery_status="skipped",
            delivery_detail="no delivery channel configured",
            headline="SQL moved.",
            did=("Closed four days.",),
            decision_for_frank="Approve the spoken block.",
            created_at=datetime(2026, 9, 13, tzinfo=UTC),
        )


def _client() -> tuple[TestClient, StubQueue]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    queue = StubQueue()
    app.dependency_overrides[get_weekly_report_queue] = lambda: queue
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), queue


def test_reports_are_listed_requested_and_read_with_closed_errors() -> None:
    client, queue = _client()
    with client:
        listed = client.get("/api/v1/reports/weekly")
        requested = client.post("/api/v1/reports/weekly", json={"week_start": "2026-09-07"})
        latest = client.post("/api/v1/reports/weekly", json={})
        read = client.get("/api/v1/reports/weekly/2026-09-07")
        queue.error = ReportInvalid("internal")
        invalid = client.post("/api/v1/reports/weekly", json={})
        queue.error = ReportConflict("internal")
        again = client.post("/api/v1/reports/weekly", json={})

    assert listed.status_code == 200 and listed.json()["items"][0]["delivery_status"] == "skipped"
    assert listed.headers["cache-control"] == "no-store"
    assert requested.status_code == 202 and requested.json()["status"] == "queued"
    assert latest.status_code == 202 and queue.requested == [date(2026, 9, 7), None]
    assert read.status_code == 200 and read.json()["headline"] == "SQL moved."
    assert invalid.status_code == 422 and invalid.json()["code"] == "report_invalid"
    assert again.status_code == 409 and again.json()["code"] == "report_conflict"
    assert "internal" not in invalid.text + again.text
