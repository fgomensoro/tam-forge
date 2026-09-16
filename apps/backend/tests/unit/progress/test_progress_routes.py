from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.progress.routes import get_progress_service
from tamforge_backend.progress.schemas import (
    ProgressAssessment,
    ProgressInterview,
    ProgressResponse,
    ProgressSkill,
    ProgressSkillPoint,
    ProgressWeek,
)
from tamforge_backend.progress.service import (
    ProgressUnavailable,
    average_dimension_score,
    weekly_minutes,
)

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[int] = []

    async def read(self, *, owner_id: int) -> ProgressResponse:
        self.calls.append(owner_id)
        if self.error is not None:
            raise self.error
        return ProgressResponse(
            skills=(
                ProgressSkill(
                    slug="structured_troubleshooting",
                    name="Structured troubleshooting",
                    baseline=Decimal("2"),
                    month_one_target=Decimal("2.5"),
                    final_target=Decimal("3"),
                    latest_level=Decimal("2.750"),
                    confidence="medium",
                    trend="up",
                    points=(
                        ProgressSkillPoint(
                            snapshot_date=date(2026, 9, 16), estimated_level=Decimal("2.750")
                        ),
                    ),
                ),
            ),
            weeks=(
                ProgressWeek(
                    week_start=date(2026, 9, 14),
                    planned_minutes=600,
                    focused_minutes=420,
                    study_days=5,
                    closed_days=3,
                ),
            ),
            assessments=(
                ProgressAssessment(
                    review_id=3,
                    activity_id=41,
                    task_stable_id="p0-w00-d00-warmup",
                    local_date=date(2026, 9, 16),
                    rubric_slug="tam_block",
                    block="tam_case",
                    average_score=Decimal("3.00"),
                    dimension_count=6,
                    verdict="Correct on delivery.",
                    reviewed_at=datetime(2026, 9, 16, 12, tzinfo=UTC),
                ),
            ),
            assessment_days=(),
            interviews=(
                ProgressInterview(
                    interview_id=2,
                    company="Coframe",
                    role="TAM",
                    stage="screen",
                    starts_at=datetime(2026, 9, 10, 17, tzinfo=UTC),
                    status="completed",
                    recording_count=1,
                ),
            ),
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
    app.dependency_overrides[get_progress_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    return TestClient(app), service


def test_progress_is_one_owner_scoped_read_with_every_section() -> None:
    client, service = _client()
    with client:
        response = client.get("/api/v1/progress")
        write = client.post("/api/v1/progress", json={})

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["skills"][0]["latest_level"] == "2.750"
    assert payload["skills"][0]["points"][0]["snapshot_date"] == "2026-09-16"
    assert payload["weeks"][0]["planned_minutes"] == 600
    assert payload["assessments"][0]["average_score"] == "3.00"
    assert payload["assessments"][0]["block"] == "tam_case"
    assert payload["assessment_days"] == []
    assert payload["interviews"][0]["company"] == "Coframe"
    assert write.status_code == 405
    assert service.calls == [1]


def test_an_unavailable_store_is_a_closed_problem() -> None:
    client, service = _client()
    service.error = ProgressUnavailable("internal detail")
    with client:
        response = client.get("/api/v1/progress")

    assert response.status_code == 503
    assert response.json()["code"] == "progress_unavailable"
    assert "internal detail" not in response.text


def test_weeks_fold_study_days_from_monday_and_count_closed_days() -> None:
    weeks = weekly_minutes(
        [
            (date(2026, 9, 16), 120, 90, "closed"),
            (date(2026, 9, 20), 60, 0, "planned"),
            (date(2026, 9, 21), 120, 120, "closed"),
            (date(2026, 9, 15), 120, 100, "closed"),
        ]
    )
    assert [w.week_start for w in weeks] == [date(2026, 9, 14), date(2026, 9, 21)]
    assert (weeks[0].planned_minutes, weeks[0].focused_minutes) == (300, 190)
    assert (weeks[0].study_days, weeks[0].closed_days) == (3, 2)
    assert weeks[1].closed_days == 1


def test_the_average_dimension_score_survives_odd_outcomes() -> None:
    assert average_dimension_score({}) == (Decimal("0"), 0)
    assert average_dimension_score({"dimensions": "no"}) == (Decimal("0"), 0)
    assert average_dimension_score(
        {"dimensions": [{"slug": "a", "score": "3"}, {"slug": "b", "score": 2.5}]}
    ) == (Decimal("2.75"), 2)
