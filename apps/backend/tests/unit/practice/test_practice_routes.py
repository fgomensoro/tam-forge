"""Practice answer endpoints: store-and-queue, list, and closed errors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.practice.routes import get_practice_service
from tamforge_backend.practice.schemas import (
    PracticeAnswerCommand,
    PracticeAnswerPage,
    PracticeAnswerResponse,
    PracticeDimensionResponse,
    PracticeFixResponse,
)
from tamforge_backend.practice.service import (
    PracticeInvalid,
    PracticeNotFound,
    PracticeUnavailable,
    learner_answer,
    practice_review_idempotency_key,
)

RECORDING = UUID("10f3d9de-b6dd-48a4-8f01-bd570e17de22")
OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


def _answer(status: str) -> PracticeAnswerResponse:
    ready = status == "ready"
    return PracticeAnswerResponse(
        id=4,
        question="Why are you leaving?",
        recording_id=RECORDING,
        reference_material_id=2,
        status=status,  # type: ignore[arg-type]
        failure_category=None,
        model="claude-fable-5-1" if ready else None,
        dimensions=(
            PracticeDimensionResponse(
                slug="answer_clarity",
                name="Answer clarity and structure",
                score=Decimal("3.0"),
                evidence="I hit the ceiling",
                note="Direct.",
            ),
        )
        if ready
        else (),
        strengths=("Opens with the number.",) if ready else (),
        fixes=(PracticeFixResponse(heard="at scale", say_instead="at real scale", why="Anchor."),)
        if ready
        else (),
        reference_coverage="The team anchor is missing." if ready else "",
        readiness="drilling" if ready else None,
        created_at=datetime(2026, 9, 18, tzinfo=UTC),
        reviewed_at=datetime(2026, 9, 18, 0, 5, tzinfo=UTC) if ready else None,
    )


class StubPractice:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.submitted: list[PracticeAnswerCommand] = []

    async def submit(
        self, *, owner_id: int, command: PracticeAnswerCommand
    ) -> PracticeAnswerResponse:
        if self.error is not None:
            raise self.error
        self.submitted.append(command)
        return _answer("awaiting_transcript")

    async def list(self, *, owner_id: int) -> PracticeAnswerPage:
        return PracticeAnswerPage(items=(_answer("ready"),))


def _client() -> tuple[TestClient, StubPractice]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubPractice()
    app.dependency_overrides[get_practice_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_an_answer_is_stored_then_listed_and_errors_stay_closed() -> None:
    client, service = _client()
    body = {"question": "Why are you leaving?", "recording_id": str(RECORDING)}
    with client:
        stored = client.post("/api/v1/practice-answers", json={**body, "reference_material_id": 2})
        listed = client.get("/api/v1/practice-answers")
        unknown_field = client.post("/api/v1/practice-answers", json={**body, "score": 4})
        service.error = PracticeNotFound("internal")
        uploading = client.post("/api/v1/practice-answers", json=body)
        service.error = PracticeInvalid("internal")
        invalid = client.post("/api/v1/practice-answers", json=body)
        service.error = PracticeUnavailable("internal")
        down = client.post("/api/v1/practice-answers", json=body)

    assert stored.status_code == 202 and stored.json()["status"] == "awaiting_transcript"
    assert stored.headers["cache-control"] == "no-store"
    assert service.submitted[0].reference_material_id == 2
    item = listed.json()["items"][0]
    assert item["status"] == "ready" and item["dimensions"][0]["score"] == "3.0"
    assert item["fixes"][0]["say_instead"] == "at real scale"
    assert unknown_field.status_code == 422
    assert uploading.status_code == 404 and uploading.json()["code"] == "practice_not_found"
    assert invalid.status_code == 422 and invalid.json()["code"] == "practice_invalid"
    assert down.status_code == 503
    assert "internal" not in uploading.text + invalid.text + down.text


def test_only_the_learners_turns_are_the_answer_and_the_key_follows_the_transcript() -> None:
    turns = [
        {"speaker": "other", "start_ms": 0, "text": "Why are you leaving?"},
        {"speaker": "learner", "start_ms": 2100, "text": " I hit the ceiling. "},
        {"speaker": "learner", "start_ms": 5000, "text": "  "},
        {"speaker": "learner", "start_ms": 6000, "text": "I want scale."},
    ]
    assert learner_answer(turns) == "I hit the ceiling. I want scale."
    assert learner_answer([]) == ""
    key = practice_review_idempotency_key(answer_id=4, transcript_sha256="ab" * 32)
    assert key == "claude-practice-a4-abababababababab"
