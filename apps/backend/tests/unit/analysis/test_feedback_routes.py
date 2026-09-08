"""HTTP contract for the gated feedback read."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
from tamforge_backend.main import create_app
from tamforge_protocol.agents import FeedbackRead

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=APPROVED_GITHUB_USER_ID,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubFeedbackRepository:
    def __init__(self, read: FeedbackRead | None = None) -> None:
        self.read = read or FeedbackRead(status="processing", activity_id=7, attempt_id=9)
        self.calls: list[tuple[int, int, int]] = []

    async def feedback(self, *, owner_id: int, activity_id: int, attempt_id: int) -> FeedbackRead:
        self.calls.append((owner_id, activity_id, attempt_id))
        return self.read


def client(repository):
    from tamforge_backend.analysis.routes import get_feedback_repository

    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    app.dependency_overrides[get_feedback_repository] = lambda: repository
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    return TestClient(app)


def test_processing_feedback_carries_no_analysis():
    repository = StubFeedbackRepository()
    response = client(repository).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["english"] is None and body["tam"] is None
    assert repository.calls == [(1, 7, 9)]


def test_withheld_feedback_reports_only_a_closed_reason():
    repository = StubFeedbackRepository(
        FeedbackRead(
            status="needs_attention",
            activity_id=7,
            attempt_id=9,
            withheld_reason="self_review_pending",
        )
    )
    body = client(repository).get("/api/v1/activities/7/attempts/9/feedback").json()
    assert body["withheld_reason"] == "self_review_pending"
    assert body["english"] is None and body["tam"] is None


def released_feedback() -> FeedbackRead:
    """A ready read, so the one path that actually hands over analysis is exercised."""
    from tamforge_protocol.agents import (
        AnalysisVersions,
        EnglishAnalysisV1,
        PinnedRecord,
        TAMAnalysisV1,
    )

    unscored = {
        "availability": "not_applicable",
        "score": None,
        "reason_code": "not_exercised",
        "explanation": "This dimension was not exercised.",
    }
    scored = {
        "availability": "scored",
        "score": 3,
        "rationale": "Supported by prepared text.",
        "observations": [
            {
                "statement": "The answer named the customer impact.",
                "attribution": "observed_content",
                "availability": "available",
                "confidence": "0.8",
                "references": [
                    {
                        "kind": "attempt_text",
                        "attempt_id": 9,
                        "commitment_sha256": "a" * 64,
                        "json_pointer": "/output/draft_markdown",
                        "start_codepoint": 0,
                        "end_codepoint": 4,
                    }
                ],
            }
        ],
    }
    common = {
        "activity_id": 7,
        "attempt_id": 9,
        "config_version_key": "seed-v1",
        "rubric_slug": "tam_case",
        "rubric_version": "seed-v1",
    }
    english = EnglishAnalysisV1.model_validate(
        {
            "analysis_kind": "english_analysis",
            "schema_version": "english-analysis-v1",
            "source_mode": "written",
            **common,
            "dimensions": {
                "communication_effectiveness": scored,
                "accuracy": unscored,
                "vocabulary": unscored,
                "fluency": {
                    "availability": "unavailable",
                    "score": None,
                    "reason_code": "speech_pipeline_unavailable",
                    "explanation": "Speech pipeline is not installed.",
                },
                "pronunciation_intelligibility": {
                    "availability": "unavailable",
                    "score": None,
                    "reason_code": "pronunciation_not_measured",
                    "explanation": "Calibrated diagnostic did not run.",
                },
                "listening": {
                    "availability": "not_applicable",
                    "score": None,
                    "reason_code": "written_source",
                    "explanation": "Written submission has no listening evidence.",
                },
            },
        }
    )
    tam_keys = (
        "structure",
        "relevance",
        "customer_judgment",
        "technical_reasoning",
        "business_framing",
        "trade_offs",
        "audience_adaptation",
        "decision_quality",
    )
    tam = TAMAnalysisV1.model_validate(
        {
            "analysis_kind": "tam_analysis",
            "schema_version": "tam-analysis-v1",
            **common,
            "dimensions": {"correctness": scored, **{key: unscored for key in tam_keys}},
        }
    )
    pin = PinnedRecord(id=1, content_hash="a" * 64)
    return FeedbackRead(
        status="ready",
        activity_id=7,
        attempt_id=9,
        versions=AnalysisVersions(
            model_run=pin, prompt=pin, output_schema=pin, rubric_binding=pin
        ),
        english=english,
        tam=tam,
    )


def test_ready_feedback_hands_over_both_analyses_and_their_versions():
    body = client(StubFeedbackRepository(released_feedback())).get(
        "/api/v1/activities/7/attempts/9/feedback"
    ).json()
    assert body["status"] == "ready"
    assert body["withheld_reason"] is None
    assert body["english"]["analysis_kind"] == "english_analysis"
    assert body["tam"]["analysis_kind"] == "tam_analysis"
    assert body["versions"]["model_run"]["id"] == 1
    assert (
        body["english"]["dimensions"]["communication_effectiveness"]["observations"][0][
            "references"
        ][0]["attempt_id"]
        == 9
    )


def test_feedback_read_is_never_stored_by_a_cache():
    response = client(StubFeedbackRepository()).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.headers["Cache-Control"] == "no-store"


def test_missing_attempt_is_a_problem_document():
    from tamforge_backend.analysis.repository import FeedbackNotFound

    class Missing(StubFeedbackRepository):
        async def feedback(self, *, owner_id, activity_id, attempt_id):
            raise FeedbackNotFound()

    response = client(Missing()).get("/api/v1/activities/7/attempts/9/feedback")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "feedback_not_found"


def test_unauthenticated_read_is_rejected():
    from tamforge_backend.analysis.routes import get_feedback_repository
    from tamforge_backend.auth.service import Unauthenticated

    def missing_owner() -> None:
        raise Unauthenticated("authentication required")

    app = create_app(
        Settings(
            environment="test",
            github_user_id=APPROVED_GITHUB_USER_ID,
            secure_cookies=False,
            _env_file=None,
        )
    )
    app.dependency_overrides[get_feedback_repository] = lambda: StubFeedbackRepository()
    app.dependency_overrides[get_authenticated_owner] = missing_owner

    # A bare TestClient never runs the app lifespan, so app.state.database/settings
    # stay unset; entering the client as a context manager triggers startup the same
    # way test_sql_execution_routes_require_an_authenticated_owner does.
    with TestClient(app) as client:
        response = client.get("/api/v1/activities/7/attempts/9/feedback")
    assert response.status_code in (401, 403)
