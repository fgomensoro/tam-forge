from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.classes.analysis import learner_text, render_turns
from tamforge_backend.classes.routes import get_class_analysis_service
from tamforge_backend.classes.schemas import ClassAnalysisResponse, ClassAspectResponse
from tamforge_backend.classes.service import ClassConflict, ClassInvalid
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


class StubAnalyses:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.requested: list[int] = []

    async def request(self, *, owner_id: int, class_id: int) -> ClassAnalysisResponse:
        if self.error is not None:
            raise self.error
        self.requested.append(class_id)
        return ClassAnalysisResponse(class_id=class_id, status="queued")

    async def read(self, *, owner_id: int, class_id: int) -> ClassAnalysisResponse:
        return ClassAnalysisResponse(
            class_id=class_id,
            status="ready",
            analysis_id=2,
            model="claude-fable-5-1",
            fluency=ClassAspectResponse(
                score=Decimal("3.0"), rationale="Keeps going.", evidence="I have"
            ),
            vocabulary=ClassAspectResponse(
                score=Decimal("2.5"), rationale="Precise.", evidence="runbook"
            ),
            progress_direction="up",
            progress_statement="Half a point up.",
            next_focus="Simple past.",
            previous_classes=1,
            created_at=datetime(2026, 9, 18, tzinfo=UTC),
        )


def _client() -> tuple[TestClient, StubAnalyses]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    service = StubAnalyses()
    app.dependency_overrides[get_class_analysis_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_an_analysis_is_requested_then_read_and_errors_stay_closed() -> None:
    client, service = _client()
    with client:
        queued = client.post("/api/v1/english-classes/3/analysis")
        read = client.get("/api/v1/english-classes/3/analysis")
        service.error = ClassInvalid("internal")
        invalid = client.post("/api/v1/english-classes/3/analysis")
        service.error = ClassConflict("internal")
        again = client.post("/api/v1/english-classes/3/analysis")

    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    assert queued.headers["cache-control"] == "no-store"
    assert read.status_code == 200
    assert read.json()["fluency"]["score"] == "3.0" and read.json()["previous_classes"] == 1
    assert invalid.status_code == 422 and invalid.json()["code"] == "class_invalid"
    assert again.status_code == 409
    assert "internal" not in invalid.text + again.text
    assert service.requested == [3]


def test_turns_render_with_the_teacher_label_and_learner_text_is_gathered() -> None:
    turns = [
        {"speaker": "other", "start_ms": 0, "text": "How was your week?"},
        {"speaker": "learner", "start_ms": 2100, "text": "Good."},
        {"speaker": "learner", "start_ms": 5000, "text": "  "},
    ]
    assert render_turns(turns) == "[0] Teacher: How was your week?\n[2100] Learner: Good."
    assert learner_text(turns).strip() == "Good."
