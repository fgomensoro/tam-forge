from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.reviews.routes import get_review_service
from tamforge_backend.reviews.schemas import ActivityReviewResponse, ReviewedDimensionResponse
from tamforge_backend.reviews.service import ReviewConflict, ReviewNotFound, ReviewsUnavailable

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


def _ready() -> ActivityReviewResponse:
    return ActivityReviewResponse(
        activity_id=41,
        status="ready",
        review_id=3,
        attempt_id=11,
        rubric_slug="tam_block",
        rubric_version="seed-v1",
        model="claude-fable-5-1",
        verdict="Correct, weak close.",
        dimensions=(
            ReviewedDimensionResponse(
                slug="correctness",
                name="Correctness",
                score=Decimal("3.5"),
                maximum=Decimal(4),
                rationale="Right idea.",
                evidence="200 means accepted",
            ),
        ),
        strengths=(),
        corrections=(),
        next_practice="Again aloud.",
        evidence_status="recorded",
        evidence_event_ids=(9, 10),
        created_at=datetime(2026, 9, 16, tzinfo=UTC),
    )


class StubService:
    def __init__(self) -> None:
        self.requested: list[int] = []
        self.error: Exception | None = None

    async def read(self, *, owner_id: int, activity_id: int) -> ActivityReviewResponse:
        assert owner_id == 1 and activity_id == 41
        if self.error is not None:
            raise self.error
        return _ready()

    async def request(self, *, owner_id: int, activity_id: int) -> ActivityReviewResponse:
        assert owner_id == 1 and activity_id == 41
        if self.error is not None:
            raise self.error
        self.requested.append(activity_id)
        return ActivityReviewResponse(activity_id=41, status="queued")


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
    app.dependency_overrides[get_review_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_read_and_request_round_trip_without_caching() -> None:
    client, service = _client()
    with client:
        read = client.get("/api/v1/activities/41/review")
        requested = client.post("/api/v1/activities/41/review")

    assert read.status_code == 200 and read.json()["status"] == "ready"
    assert read.json()["dimensions"][0]["score"] == "3.5"
    assert read.headers["cache-control"] == "no-store"
    assert requested.status_code == 200 and requested.json()["status"] == "queued"
    assert service.requested == [41]


def test_problems_map_to_closed_codes() -> None:
    client, service = _client()
    with client:
        service.error = ReviewNotFound("none")
        missing = client.get("/api/v1/activities/41/review")
        service.error = ReviewConflict("already")
        conflict = client.post("/api/v1/activities/41/review")
        service.error = ReviewsUnavailable("down")
        unavailable = client.post("/api/v1/activities/41/review")

    assert missing.status_code == 404 and missing.json()["code"] == "review_not_found"
    assert conflict.status_code == 409 and conflict.json()["code"] == "review_conflict"
    assert unavailable.status_code == 503 and unavailable.json()["code"] == "reviews_unavailable"
