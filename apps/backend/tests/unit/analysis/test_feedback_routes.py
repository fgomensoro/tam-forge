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
