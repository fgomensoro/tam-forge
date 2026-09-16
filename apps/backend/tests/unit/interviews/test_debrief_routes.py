from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.interviews.debriefs import render_turns
from tamforge_backend.interviews.routes import get_debrief_service
from tamforge_backend.interviews.schemas import DebriefFindingResponse, InterviewDebriefResponse
from tamforge_backend.interviews.service import InterviewConflict, InterviewInvalid
from tamforge_backend.main import create_app

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubDebriefs:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.requested: list[int] = []

    async def request(self, *, owner_id: int, interview_id: int) -> InterviewDebriefResponse:
        if self.error is not None:
            raise self.error
        self.requested.append(interview_id)
        return InterviewDebriefResponse(interview_id=interview_id, status="queued")

    async def read(self, *, owner_id: int, interview_id: int) -> InterviewDebriefResponse:
        return InterviewDebriefResponse(
            interview_id=interview_id,
            status="ready",
            debrief_id=4,
            transcript_source="transcript_only",
            model="claude-opus-5",
            summary="Clear root cause.",
            strengths=(
                DebriefFindingResponse(
                    statement="Names the cause.", evidence="traced", skill_slug="x"
                ),
            ),
            hiring_progression="Advanced.",
            created_at=datetime(2026, 9, 16, tzinfo=UTC),
        )


def _client() -> tuple[TestClient, StubDebriefs]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubDebriefs()
    app.dependency_overrides[get_debrief_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_a_debrief_is_requested_then_read_and_errors_stay_closed() -> None:
    client, service = _client()
    with client:
        queued = client.post("/api/v1/interviews/7/debrief")
        read = client.get("/api/v1/interviews/7/debrief")
        service.error = InterviewInvalid("internal")
        invalid = client.post("/api/v1/interviews/7/debrief")
        service.error = InterviewConflict("internal")
        again = client.post("/api/v1/interviews/7/debrief")

    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    assert queued.headers["cache-control"] == "no-store"
    assert read.status_code == 200
    assert read.json()["status"] == "ready" and read.json()["summary"] == "Clear root cause."
    assert read.json()["transcript_source"] == "transcript_only"
    assert invalid.status_code == 422 and invalid.json()["code"] == "interview_invalid"
    assert again.status_code == 409 and again.json()["code"] == "interview_conflict"
    assert "internal" not in invalid.text + again.text
    assert service.requested == [7]


def test_turns_render_with_or_without_timestamps() -> None:
    turns = [
        {"speaker": "other", "start_ms": 0, "text": "Hi."},
        {"speaker": "learner", "start_ms": 1200, "text": "Hello."},
        {"speaker": "learner", "start_ms": 2000, "text": "   "},
    ]
    assert render_turns(turns, with_time=True) == "[0] Interviewer: Hi.\n[1200] Learner: Hello."
    assert render_turns(turns, with_time=False) == "Interviewer: Hi.\nLearner: Hello."


def test_the_timeline_orders_interviews_and_finds_recurring_gaps() -> None:
    from decimal import Decimal
    from types import SimpleNamespace

    from tamforge_backend.interviews.debriefs import build_timeline

    def outcome(clarity: str, gap_skill: str) -> dict[str, object]:
        return {
            "summary": "s",
            "dimensions": [
                {"slug": "answer_clarity", "score": clarity, "rationale": "x"},
                {"slug": "technical_examples", "score": "3", "rationale": "x"},
                {"slug": "english_accuracy", "score": "3", "rationale": "x"},
                {"slug": "follow_up_handling", "score": "2.5", "rationale": "x"},
            ],
            "strengths": [
                {"statement": "a", "evidence": "q", "skill_slug": "x"},
                {"statement": "b", "evidence": "q", "skill_slug": "x"},
            ],
            "gaps": [
                {"statement": "No impact stated.", "evidence": "q", "skill_slug": gap_skill},
                {"statement": "No close.", "evidence": "q", "skill_slug": "structure"},
            ],
            "skills_affected": [{"skill_slug": gap_skill, "direction": "flat", "evidence": "q"}],
            "next_week_practice": [{"description": "d", "skill_slug": gap_skill, "minutes": 20}],
            "hiring_progression": "Advanced.",
        }

    def interview(id_: int, company: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=id_,
            company=company,
            role="TAM",
            stage="screen",
            starts_at=datetime(2026, 9, id_, tzinfo=UTC),
            status="completed",
        )

    timeline = build_timeline(
        [
            (interview(1, "Acme"), outcome("2.5", "business_value_framing")),  # type: ignore[list-item]
            (interview(2, "Beta"), None),  # type: ignore[list-item]
            (interview(3, "Coframe"), outcome("3.5", "business_value_framing")),  # type: ignore[list-item]
        ]
    )
    assert [i.company for i in timeline.items] == ["Acme", "Beta", "Coframe"]
    assert timeline.debriefed == 2 and timeline.items[1].has_debrief is False
    clarity = next(t for t in timeline.dimension_trends if t.slug == "answer_clarity")
    assert clarity.latest == Decimal("3.5") and clarity.delta_from_first == Decimal("1.0")
    assert [s.slug for s in clarity.scores] == ["1", "3"]
    assert [g.skill_slug for g in timeline.recurring_gaps] == [
        "business_value_framing",
        "structure",
    ]
    assert timeline.recurring_gaps[0].interview_count == 2
    assert timeline.recurring_gaps[0].statements == ("No impact stated.",)
