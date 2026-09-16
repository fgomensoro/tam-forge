"""The monthly report role, its due-month rule, its rendering, and its routes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from tamforge_backend.agents.roles.monthly_report import (
    MonthlyReportRequest,
    MonthlySkillInput,
    render_monthly_report_prompt,
    validate_monthly_report,
)
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.reports.monthly import (
    due_month,
    month_end_of,
    previous_month,
    render_monthly_text,
)
from tamforge_backend.reports.routes import get_monthly_report_queue
from tamforge_backend.reports.schemas import MonthlyReportPage, MonthlyReportResponse
from tamforge_backend.reports.service import ReportConflict, ReportInvalid

SKILLS = (
    MonthlySkillInput(
        "sql_reconciliation",
        "SQL",
        Decimal("2"),
        Decimal("3"),
        Decimal("3.5"),
        Decimal("2"),
        Decimal("2.5"),
        6,
    ),
    MonthlySkillInput(
        "tam_english",
        "English",
        Decimal("2"),
        Decimal("2.5"),
        Decimal("3"),
        Decimal("2"),
        Decimal("2"),
        1,
    ),
    MonthlySkillInput(
        "structured_troubleshooting",
        "Troubleshooting",
        Decimal("2"),
        Decimal("2.5"),
        Decimal("3"),
        Decimal("2"),
        Decimal("2.75"),
        4,
    ),
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
        "headline": "SQL moved; English did not.",
        "trajectory": [
            {"skill_slug": "sql_reconciliation", "status": "behind", "note": "Half short."},
            {"skill_slug": "tam_english", "status": "behind", "note": "No speech."},
            {"skill_slug": "structured_troubleshooting", "status": "ahead", "note": "Past target."},
        ],
        "largest_gaps": ["sql_reconciliation", "tam_english"],
        "coverage_verdict": "Twelve of twenty covered.",
        "exit_criteria_verdict": "Not met yet.",
        "best_evidence": ["The webhook case."],
        "recommendation": "reforecast",
        "recommendation_reasoning": "Two skills half a point short.",
        "next_month_priorities": ["One spoken SQL explanation per week."],
    }
    base.update(overrides)
    return base


def test_gaps_are_the_ledgers_and_every_skill_appears_once() -> None:
    assert validate_monthly_report(_payload(), skills=SKILLS) == ()
    assert (
        validate_monthly_report(_payload(largest_gaps=["sql_reconciliation"]), skills=SKILLS) == ()
    )
    wrong_order = _payload(largest_gaps=["tam_english", "sql_reconciliation"])
    assert "in order" in validate_monthly_report(wrong_order, skills=SKILLS)[0]
    outside = _payload(largest_gaps=["charisma"])
    assert "catalog" in validate_monthly_report(outside, skills=SKILLS)[0]
    missing = _payload(trajectory=_payload()["trajectory"][:2])  # type: ignore[index]
    assert "every skill exactly once" in validate_monthly_report(missing, skills=SKILLS)[0]
    applied = _payload(headline="I applied the reforecast.")
    assert "never applies" in validate_monthly_report(applied, skills=SKILLS)[0]
    assert SKILLS[0].gap_to_month_one == Decimal("0.5") and SKILLS[2].gap_to_final == Decimal(
        "0.25"
    )


def test_the_prompt_ranks_skills_by_gap_and_names_the_rules() -> None:
    prompt = render_monthly_report_prompt(
        MonthlyReportRequest(
            month_start=date(2026, 9, 1),
            month_end=date(2026, 9, 30),
            skills=SKILLS,
            aggregates={"closed_days": 18},
            coverage={"completed": 12},
            assessments=("2026-09-12: 1/4 scored",),
        )
    )
    first = prompt.index("- sql_reconciliation:")
    second = prompt.index("- tam_english:")
    third = prompt.index("- structured_troubleshooting:")
    assert first < second < third
    assert "gap 0.5; final gap 1.0" in prompt
    assert "Coverage ledger:" in prompt and "Saturday assessments:" in prompt
    assert "Never apply a change" in prompt


def test_the_due_month_turns_over_on_the_last_evening_local_time() -> None:
    assert due_month(datetime(2026, 10, 1, 0, 59, tzinfo=UTC), "America/Los_Angeles") == date(
        2026, 9, 1
    )
    assert due_month(datetime(2026, 10, 1, 1, 0, tzinfo=UTC), "America/Los_Angeles") == date(
        2026, 9, 1
    )
    assert due_month(datetime(2026, 9, 16, 12, tzinfo=UTC), "UTC") == date(2026, 8, 1)
    assert due_month(datetime(2026, 9, 30, 18, tzinfo=UTC), "UTC") == date(2026, 9, 1)
    assert month_end_of(date(2026, 2, 1)) == date(2026, 2, 28)
    assert previous_month(date(2026, 1, 1)) == date(2025, 12, 1)


def test_the_text_rendering_leads_with_the_largest_gaps() -> None:
    text = render_monthly_text("2026-09-01", "2026-09-30", _payload())
    assert "Largest gaps first: sql_reconciliation, tam_english" in text
    assert "- structured_troubleshooting: ahead; Past target." in text
    assert "Recommendation (reforecast): Two skills half a point short." in text


class StubQueue:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.requested: list[date | None] = []

    async def list(self, *, owner_id: int, limit: int = 12) -> MonthlyReportPage:
        return MonthlyReportPage(items=(self._ready(),))

    async def request(self, *, owner_id: int, month_start: date | None) -> MonthlyReportResponse:
        if self.error is not None:
            raise self.error
        self.requested.append(month_start)
        return MonthlyReportResponse(
            month_start=month_start or date(2026, 8, 1),
            month_end=date(2026, 8, 31),
            status="queued",
        )

    async def read(self, *, owner_id: int, month_start: date) -> MonthlyReportResponse:
        return self._ready()

    @staticmethod
    def _ready() -> MonthlyReportResponse:
        return MonthlyReportResponse(
            month_start=date(2026, 8, 1),
            month_end=date(2026, 8, 31),
            status="ready",
            report_id=1,
            model="claude-fable-5-1",
            delivery_status="skipped",
            headline="SQL moved.",
            largest_gaps=("sql_reconciliation",),
            recommendation="keep",
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
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
    app.dependency_overrides[get_monthly_report_queue] = lambda: queue
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), queue


def test_monthly_reports_are_listed_requested_and_read() -> None:
    client, queue = _client()
    with client:
        listed = client.get("/api/v1/reports/monthly")
        requested = client.post("/api/v1/reports/monthly", json={"month_start": "2026-08-01"})
        read = client.get("/api/v1/reports/monthly/2026-08-01")
        queue.error = ReportInvalid("internal")
        invalid = client.post("/api/v1/reports/monthly", json={})
        queue.error = ReportConflict("internal")
        again = client.post("/api/v1/reports/monthly", json={})

    assert listed.status_code == 200 and listed.json()["items"][0]["largest_gaps"] == [
        "sql_reconciliation"
    ]
    assert requested.status_code == 202 and queue.requested == [date(2026, 8, 1)]
    assert read.status_code == 200 and read.json()["recommendation"] == "keep"
    assert invalid.status_code == 422 and again.status_code == 409
    assert "internal" not in invalid.text + again.text
