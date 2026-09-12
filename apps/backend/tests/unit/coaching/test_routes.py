from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.coaching.routes import get_coach_thread_service
from tamforge_backend.coaching.schemas import (
    CoachEvidenceProposal,
    CoachMessageResponse,
    CoachThreadResponse,
)
from tamforge_backend.coaching.service import CoachingConflict, CoachingUnavailable
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


def _thread(messages: int = 0) -> CoachThreadResponse:
    items = [
        CoachMessageResponse(
            id=10 + index,
            speaker="coach" if index % 2 else "learner",
            text="hola" if index % 2 == 0 else "Good; add the backoff rule.",
            next_step=None
            if index % 2 == 0
            else "Submit the mandatory self-review for this block.",
            proposed_evidence=[]
            if index % 2 == 0
            else [
                CoachEvidenceProposal(
                    index=0, kind="note", text="Backoff with jitter.", accepted=False
                )
            ],
            created_at=datetime(2026, 9, 12, tzinfo=UTC),
        )
        for index in range(messages)
    ]
    return CoachThreadResponse(
        activity_id=41,
        thread_id=7 if messages else None,
        coaching_allowed=True,
        committed=True,
        next_step="Submit the mandatory self-review for this block.",
        messages=items,
    )


class StubService:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.accepted: list[tuple[int, int]] = []
        self.error: Exception | None = None

    async def thread(self, *, owner_id: int, activity_id: int) -> CoachThreadResponse:
        assert owner_id == 1 and activity_id == 41
        return _thread(0)

    async def send(self, *, owner_id: int, activity_id: int, text: str) -> CoachThreadResponse:
        assert owner_id == 1 and activity_id == 41
        if self.error is not None:
            raise self.error
        self.sent.append(text)
        return _thread(2)

    async def accept_evidence(
        self, *, owner_id: int, activity_id: int, message_id: int, index: int
    ) -> CoachThreadResponse:
        assert owner_id == 1 and activity_id == 41
        self.accepted.append((message_id, index))
        return _thread(2)


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
    app.dependency_overrides[get_coach_thread_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_thread_read_send_and_accept_round_trip_without_caching() -> None:
    client, service = _client()
    with client:
        empty = client.get("/api/v1/activities/41/coach")
        sent = client.post("/api/v1/activities/41/coach/messages", json={"text": "hola"})
        accepted = client.post(
            "/api/v1/activities/41/coach/evidence", json={"message_id": 11, "index": 0}
        )

    assert empty.status_code == 200 and empty.json()["messages"] == []
    assert empty.headers["cache-control"] == "no-store"
    assert sent.status_code == 200
    assert [item["speaker"] for item in sent.json()["messages"]] == ["learner", "coach"]
    assert sent.json()["messages"][1]["proposed_evidence"][0]["kind"] == "note"
    assert service.sent == ["hola"]
    assert accepted.status_code == 200 and service.accepted == [(11, 0)]


def test_problems_map_to_closed_codes() -> None:
    client, service = _client()
    with client:
        service.error = CoachingConflict("commit first")
        conflict = client.post("/api/v1/activities/41/coach/messages", json={"text": "hola"})
        service.error = CoachingUnavailable("down")
        unavailable = client.post("/api/v1/activities/41/coach/messages", json={"text": "hola"})
        invalid = client.post("/api/v1/activities/41/coach/messages", json={"text": ""})

    assert conflict.status_code == 409 and conflict.json()["code"] == "coaching_not_allowed"
    assert unavailable.status_code == 503 and unavailable.json()["code"] == "coach_unavailable"
    assert invalid.status_code == 422
