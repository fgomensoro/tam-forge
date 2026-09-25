from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.coaching.routes import get_general_coach_service
from tamforge_backend.coaching.schemas import (
    CoachMessageResponse,
    GeneralCoachContext,
    GeneralCoachThreadResponse,
)
from tamforge_backend.coaching.service import CoachingUnavailable
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
        self.sent: list[tuple[str, GeneralCoachContext]] = []
        self.error: Exception | None = None

    async def thread(self, *, owner_id: int) -> GeneralCoachThreadResponse:
        assert owner_id == 1
        return GeneralCoachThreadResponse(thread_id=None, messages=[])

    async def send(
        self, *, owner_id: int, text: str, context: GeneralCoachContext
    ) -> GeneralCoachThreadResponse:
        assert owner_id == 1
        if self.error is not None:
            raise self.error
        self.sent.append((text, context))
        at = datetime(2026, 9, 25, tzinfo=UTC)
        return GeneralCoachThreadResponse(
            thread_id=3,
            messages=[
                CoachMessageResponse(
                    id=1,
                    speaker="learner",
                    text=text,
                    next_step=None,
                    proposed_evidence=[],
                    created_at=at,
                ),
                CoachMessageResponse(
                    id=2,
                    speaker="coach",
                    text="Empeza por el bloque A.",
                    next_step=None,
                    proposed_evidence=[],
                    created_at=at,
                ),
            ],
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
    app.dependency_overrides[get_general_coach_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_a_fresh_owner_reads_an_empty_general_thread_without_caching() -> None:
    client, _ = _client()
    with client:
        read = client.get("/api/v1/coach")

    assert read.status_code == 200
    assert read.json() == {"thread_id": None, "messages": []}
    assert read.headers["cache-control"] == "no-store"


def test_a_message_with_its_screen_returns_both_messages() -> None:
    client, service = _client()
    with client:
        sent = client.post(
            "/api/v1/coach/messages",
            json={"text": "hola", "context": {"screen": "Today", "summary": "- block A (ready)"}},
        )

    assert sent.status_code == 200
    assert sent.headers["cache-control"] == "no-store"
    assert [item["speaker"] for item in sent.json()["messages"]] == ["learner", "coach"]
    assert service.sent == [
        ("hola", GeneralCoachContext(screen="Today", summary="- block A (ready)"))
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"text": "hola", "context": {"screen": "", "summary": ""}},
        {"text": "hola", "context": {"screen": "s" * 65}},
        {"text": "hola", "context": {"screen": "Today", "summary": "x" * 4001}},
        {"text": "hola", "context": {"screen": "Today", "extra": "no"}},
        {"text": "hola"},
        {"text": "", "context": {"screen": "Today"}},
    ],
    ids=[
        "empty-screen",
        "65-char-screen",
        "4001-char-summary",
        "unknown-key",
        "no-context",
        "no-text",
    ],
)
def test_an_invalid_message_is_refused(body: dict[str, object]) -> None:
    client, service = _client()
    with client:
        refused = client.post("/api/v1/coach/messages", json=body)

    assert refused.status_code == 422
    assert service.sent == []


def test_a_summary_of_exactly_4000_characters_is_accepted() -> None:
    client, service = _client()
    with client:
        sent = client.post(
            "/api/v1/coach/messages",
            json={"text": "hola", "context": {"screen": "s" * 64, "summary": "x" * 4000}},
        )

    assert sent.status_code == 200 and len(service.sent) == 1


def test_an_unavailable_coach_answers_a_closed_problem() -> None:
    client, service = _client()
    service.error = CoachingUnavailable("the coach needs Claude enabled on the server")
    with client:
        unavailable = client.post(
            "/api/v1/coach/messages", json={"text": "hola", "context": {"screen": "Today"}}
        )

    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "coach_unavailable"
    assert unavailable.headers["cache-control"] == "no-store"
