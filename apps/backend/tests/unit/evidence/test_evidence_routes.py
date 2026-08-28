"""Read-only HTTP contract tests for evidence history."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.evidence.routes import get_evidence_query_service
from tamforge_backend.evidence.schemas import (
    EvidenceEventPage,
    EvidenceEventResponse,
    PortfolioComponentResponse,
    PortfolioHistoryResponse,
    PortfolioScoreResponse,
    SkillListResponse,
    SkillSummaryResponse,
)
from tamforge_backend.evidence.service import EvidenceConflict
from tamforge_backend.main import create_app

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubEvidenceQueryService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.conflict = False

    @staticmethod
    def _skill() -> SkillSummaryResponse:
        return SkillSummaryResponse(
            slug="structured_troubleshooting",
            name="Structured troubleshooting",
            baseline=Decimal("2"),
            month_one_target=Decimal("2.5"),
            final_target=Decimal("3"),
            latest_snapshot=None,
        )

    @staticmethod
    def _evidence() -> EvidenceEventPage:
        return EvidenceEventPage(
            items=(
                EvidenceEventResponse(
                    id=11,
                    activity_id=7,
                    attempt_id=9,
                    skill_slug="structured_troubleshooting",
                    exercise_type="troubleshooting_case",
                    mapping_version="seed-v1",
                    formula_version="seed-v1",
                    rubric_slug="tam_case",
                    rubric_version="seed-v1",
                    evaluator="ai_rubric_reviewer",
                    practice_mode="independent_practice",
                    assistance="ai_after_committed_attempt",
                    difficulty="standard",
                    performance_score=Decimal("3"),
                    skill_impact=Decimal("0.75"),
                    effective_weight=Decimal("0.4"),
                    qualifying_for_level=True,
                    qualification_reason="qualifies",
                    raw_dimension_scores={"schema_version": 1, "scores": []},
                    occurred_at=datetime(2026, 8, 27, 18, tzinfo=UTC),
                ),
            ),
            next_cursor=None,
        )

    async def list_skills(self, **values: object) -> SkillListResponse:
        self.calls.append(("list-skills", values))
        return SkillListResponse(items=(self._skill(),))

    async def get_skill(self, **values: object) -> SkillSummaryResponse:
        self.calls.append(("get-skill", values))
        if self.conflict:
            raise EvidenceConflict("internal evidence detail must not leak")
        return self._skill()

    async def list_skill_evidence(self, **values: object) -> EvidenceEventPage:
        self.calls.append(("skill-evidence", values))
        return self._evidence()

    async def list_activity_evidence(self, **values: object) -> EvidenceEventPage:
        self.calls.append(("activity-evidence", values))
        return self._evidence()

    async def portfolio_history(self, **values: object) -> PortfolioHistoryResponse:
        self.calls.append(("portfolio", values))
        return PortfolioHistoryResponse(
            items=(
                PortfolioScoreResponse(
                    id=5,
                    activity_id=7,
                    attempt_id=9,
                    formula_version="seed-v1",
                    rubric_version="seed-v1",
                    total_score=Decimal("14"),
                    components=(
                        PortfolioComponentResponse(
                            slug="impact_risk_assessment",
                            score=Decimal("4"),
                        ),
                    ),
                    trend_basis={
                        "schema_version": 1,
                        "basis_code": "first_score",
                        "event_ids": [],
                    },
                    scored_at=datetime.combine(
                        date(2026, 8, 27),
                        datetime.min.time(),
                        UTC,
                    ),
                ),
            ),
            next_cursor=None,
        )


def _client() -> tuple[TestClient, StubEvidenceQueryService]:
    settings = Settings(
        environment="test",
        github_user_id=102269369,
        cors_origins=["https://app.example.test"],
        secure_cookies=False,
        _env_file=None,
    )
    app = create_app(settings)
    service = StubEvidenceQueryService()
    app.dependency_overrides[get_evidence_query_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    return TestClient(app), service


def test_evidence_routes_are_owner_scoped_bounded_and_read_only() -> None:
    client, service = _client()
    with client:
        skills = client.get("/api/v1/skills")
        skill = client.get("/api/v1/skills/structured_troubleshooting")
        skill_evidence = client.get(
            "/api/v1/skills/structured_troubleshooting/evidence?cursor=20&limit=10"
        )
        activity_evidence = client.get(
            "/api/v1/activities/7/evidence?cursor=20&limit=10"
        )
        portfolio = client.get("/api/v1/portfolio-judgment?cursor=20&limit=10")
        write_attempt = client.post("/api/v1/skills", json={})

    assert [
        response.status_code
        for response in (
            skills,
            skill,
            skill_evidence,
            activity_evidence,
            portfolio,
        )
    ] == [200] * 5
    assert all(
        response.headers["cache-control"] == "no-store"
        for response in (
            skills,
            skill,
            skill_evidence,
            activity_evidence,
            portfolio,
        )
    )
    assert write_attempt.status_code == 405
    assert service.calls == [
        ("list-skills", {"owner_id": 1}),
        (
            "get-skill",
            {"owner_id": 1, "skill_slug": "structured_troubleshooting"},
        ),
        (
            "skill-evidence",
            {
                "owner_id": 1,
                "skill_slug": "structured_troubleshooting",
                "cursor": 20,
                "limit": 10,
            },
        ),
        (
            "activity-evidence",
            {"owner_id": 1, "activity_id": 7, "cursor": 20, "limit": 10},
        ),
        ("portfolio", {"owner_id": 1, "cursor": 20, "limit": 10}),
    ]


def test_evidence_errors_are_closed_and_internal_details_do_not_leak() -> None:
    client, service = _client()
    service.conflict = True
    with client:
        response = client.get("/api/v1/skills/structured_troubleshooting")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "evidence_lineage_conflict"
    assert "internal evidence detail" not in response.text


def test_evidence_routes_reject_unbounded_pagination_before_service_call() -> None:
    client, service = _client()
    with client:
        response = client.get(
            "/api/v1/skills/structured_troubleshooting/evidence?limit=101"
        )

    assert response.status_code == 422
    assert service.calls == []
