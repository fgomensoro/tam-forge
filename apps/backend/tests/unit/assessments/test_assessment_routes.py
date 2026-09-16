from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from tamforge_backend.assessments.routes import get_assessment_service
from tamforge_backend.assessments.schemas import (
    AssessmentContractResult,
    AssessmentDayPage,
    AssessmentDayResult,
)
from tamforge_backend.assessments.service import (
    AssessmentsUnavailable,
    average_score,
    contract_type_for,
)
from tamforge_backend.auth.dependencies import get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app

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
        self.calls: list[tuple[int, int]] = []

    async def list(self, *, owner_id: int, limit: int = 20) -> AssessmentDayPage:
        self.calls.append((owner_id, limit))
        if self.error is not None:
            raise self.error
        return AssessmentDayPage(
            items=(
                AssessmentDayResult(
                    study_day_id=6,
                    local_date=date(2026, 8, 29),
                    day_status="closed",
                    planned_minutes=120,
                    focused_minutes=110,
                    contracts=(
                        AssessmentContractResult(
                            activity_id=61,
                            task_stable_id="m1-w1-d06-sql",
                            contract_type="saturday_sql",
                            exercise_type="sql_no_ai_timed_assessment",
                            activity_state="feedback_ready",
                            result="scored",
                            average_score=Decimal("3.00"),
                            dimension_count=6,
                            review_id=9,
                            evidence_event_ids=(1, 2),
                        ),
                        AssessmentContractResult(
                            activity_id=62,
                            task_stable_id="m1-w1-d06-case",
                            contract_type="saturday_case",
                            exercise_type="troubleshooting_case",
                            activity_state="planned",
                            result="not_attempted",
                            average_score=None,
                            dimension_count=0,
                            review_id=None,
                            evidence_event_ids=(),
                        ),
                    ),
                    scored_contracts=1,
                    average_score=Decimal("3.00"),
                ),
            )
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
    app.dependency_overrides[get_assessment_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    return TestClient(app), service


def test_assessment_days_list_each_contract_with_its_result() -> None:
    client, service = _client()
    with client:
        response = client.get("/api/v1/assessments?limit=4")
        unbounded = client.get("/api/v1/assessments?limit=99")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    day = response.json()["items"][0]
    assert day["local_date"] == "2026-08-29" and day["scored_contracts"] == 1
    assert [c["result"] for c in day["contracts"]] == ["scored", "not_attempted"]
    assert day["contracts"][0]["contract_type"] == "saturday_sql"
    assert day["contracts"][0]["average_score"] == "3.00"
    assert day["contracts"][1]["average_score"] is None
    assert unbounded.status_code == 422
    assert service.calls == [(1, 4)]


def test_an_unavailable_store_is_a_closed_problem() -> None:
    client, service = _client()
    service.error = AssessmentsUnavailable("internal detail")
    with client:
        response = client.get("/api/v1/assessments")

    assert response.status_code == 503
    assert response.json()["code"] == "assessments_unavailable"
    assert "internal detail" not in response.text


def test_contract_types_come_from_the_procedure_phase_and_scores_average_the_dimensions() -> None:
    sql = {"procedure": [{"phase": "timed_sql", "minutes": 30, "requirement": "Complete."}]}
    case = {"procedure": [{"phase": "assessed_case", "requirement": "Complete."}]}
    assert contract_type_for(sql, "sql_no_ai_timed_assessment") == "saturday_sql"
    assert contract_type_for(case, "troubleshooting_case") == "saturday_case"
    assert contract_type_for({"procedure": "no"}, "x") == "saturday_x"
    assert contract_type_for({}, None) == "saturday_unknown"
    assert average_score({"dimensions": [{"score": "3"}, {"score": "2"}]}) == (Decimal("2.50"), 2)
    assert average_score({"dimensions": []}) == (None, 0)
    assert average_score({}) == (None, 0)
