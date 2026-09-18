"""Practice answer endpoints: store-and-queue, list, and closed errors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from tamforge_backend.agents.roles.contracts import RoleContractError
from tamforge_backend.agents.roles.interview_follow_up import (
    FollowUpOutcome,
    FollowUpRequest,
    InterviewFollowUpUnavailable,
)
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.practice.routes import get_follow_up_service, get_practice_service
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
        follow_up_of=None,
        follow_up_question=None,
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


class StubFollowUps:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.requests: list[FollowUpRequest] = []

    async def decide(self, request: FollowUpRequest) -> FollowUpOutcome:
        if self.error is not None:
            raise self.error
        self.requests.append(request)
        return FollowUpOutcome(follow_up="What exactly was the ceiling?", reason="weak_point")


FOLLOW_UP_BODY = {
    "question": "Why are you leaving?",
    "reference_answer": "Four anchors.",
    "transcript": "I hit the ceiling of what I can learn there.",
    "prior_follow_ups": ["Why now?"],
}


def test_a_follow_up_is_decided_in_the_request_and_failures_stay_closed() -> None:
    client, _ = _client()
    follow_ups = StubFollowUps()
    overrides = client.app.dependency_overrides  # type: ignore[attr-defined]
    overrides[get_follow_up_service] = lambda: follow_ups
    path = "/api/v1/practice-answers/follow-up"
    with client:
        asked = client.post(path, json=FOLLOW_UP_BODY)
        bare = client.post(path, json={"question": "Why?", "transcript": "Because of scale."})
        three = client.post(path, json={**FOLLOW_UP_BODY, "prior_follow_ups": ["a?", "b?", "c?"]})
        unknown_field = client.post(path, json={**FOLLOW_UP_BODY, "recording_id": "x"})
        follow_ups.error = RoleContractError("internal")
        too_short = client.post(path, json=FOLLOW_UP_BODY)
        follow_ups.error = InterviewFollowUpUnavailable("internal")
        down = client.post(path, json=FOLLOW_UP_BODY)

    assert asked.status_code == 200
    assert asked.json() == {"follow_up": "What exactly was the ceiling?", "reason": "weak_point"}
    assert asked.headers["cache-control"] == "no-store"
    sent = follow_ups.requests[0]
    assert sent.question == "Why are you leaving?" and sent.prior_follow_ups == ("Why now?",)
    assert sent.answer_transcript == FOLLOW_UP_BODY["transcript"]
    assert sent.reference_answer == "Four anchors."
    assert bare.status_code == 200 and follow_ups.requests[1].prior_follow_ups == ()
    assert three.status_code == 422 and unknown_field.status_code == 422
    assert too_short.status_code == 422 and too_short.json()["code"] == "practice_invalid"
    assert down.status_code == 503 and down.json()["code"] == "practice_unavailable"
    assert "internal" not in too_short.text + down.text


def test_with_claude_disabled_the_follow_up_is_a_503_and_the_app_moves_on() -> None:
    client, _ = _client()
    with client:
        down = client.post("/api/v1/practice-answers/follow-up", json=FOLLOW_UP_BODY)
    assert down.status_code == 503 and down.json()["code"] == "practice_unavailable"


def test_a_follow_up_answer_names_its_question_and_its_parent_or_neither() -> None:
    client, service = _client()
    parent = "7a1f6e0c-3d52-4b8e-9c11-2f4a5b6c7d8e"
    body = {"question": "Why are you leaving?", "recording_id": str(RECORDING)}
    linked = {**body, "follow_up_question": "What was the ceiling?"}
    with client:
        both = client.post(
            "/api/v1/practice-answers", json={**linked, "follow_up_of_recording_id": parent}
        )
        only_question = client.post("/api/v1/practice-answers", json=linked)
        only_parent = client.post(
            "/api/v1/practice-answers", json={**body, "follow_up_of_recording_id": parent}
        )
        listed = client.get("/api/v1/practice-answers")

    assert both.status_code == 202
    assert service.submitted[0].follow_up_question == "What was the ceiling?"
    assert str(service.submitted[0].follow_up_of_recording_id) == parent
    assert only_question.status_code == 422 and only_parent.status_code == 422
    item = listed.json()["items"][0]
    assert item["follow_up_of"] is None and item["follow_up_question"] is None
