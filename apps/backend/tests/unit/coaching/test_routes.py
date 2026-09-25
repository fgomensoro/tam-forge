from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from tamforge_backend.agents.roles.coach import CoachService
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.coaching.routes import get_coach_thread_service
from tamforge_backend.coaching.schemas import (
    CoachDraftField,
    CoachEvidenceProposal,
    CoachMessageResponse,
    CoachThreadResponse,
    CoachWorkingContext,
)
from tamforge_backend.coaching.service import (
    CoachingConflict,
    CoachingUnavailable,
    CoachThreadService,
    _Loaded,
)
from tamforge_backend.config import Settings
from tamforge_backend.learning.models import ActivityInstance
from tamforge_backend.main import create_app
from tamforge_backend.roadmaps.models import TaskDefinition

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
        assistance_mode="none",
        next_step="Submit the mandatory self-review for this block.",
        messages=items,
    )


class StubService:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.contexts: list[CoachWorkingContext] = []
        self.accepted: list[tuple[int, int]] = []
        self.error: Exception | None = None

    async def thread(self, *, owner_id: int, activity_id: int) -> CoachThreadResponse:
        assert owner_id == 1 and activity_id == 41
        return _thread(0)

    async def send(
        self, *, owner_id: int, activity_id: int, text: str, context: CoachWorkingContext
    ) -> CoachThreadResponse:
        assert owner_id == 1 and activity_id == 41
        if self.error is not None:
            raise self.error
        self.sent.append(text)
        self.contexts.append(context)
        return _thread(2)

    async def accept_evidence(
        self,
        *,
        owner_id: int,
        activity_id: int,
        message_id: int,
        index: int,
        question: str = "",
        answer: str = "",
    ) -> CoachThreadResponse:
        assert owner_id == 1 and activity_id == 41
        self.accepted.append((message_id, index, question, answer))
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
    # The installed app sends only the text; the context defaults to empty.
    assert service.contexts == [CoachWorkingContext(step="", fields=[])]
    assert accepted.status_code == 200 and service.accepted == [(11, 0, "", "")]


def test_the_working_context_reaches_the_service() -> None:
    client, service = _client()
    with client:
        sent = client.post(
            "/api/v1/activities/41/coach/messages",
            json={
                "text": "hola",
                "context": {"step": "Do it", "fields": [{"name": "audience", "value": "CFO"}]},
            },
        )

    assert sent.status_code == 200
    assert service.contexts == [
        CoachWorkingContext(step="Do it", fields=[CoachDraftField(name="audience", value="CFO")])
    ]


@pytest.mark.parametrize(
    "context",
    [
        {"fields": [{"name": f"f{i}", "value": "x"} for i in range(21)]},
        {"fields": [{"name": "n" * 65, "value": "x"}]},
        {"fields": [{"name": "", "value": "x"}]},
        {"fields": [{"name": "a", "value": "x" * 4001}]},
        {"step": "s" * 201},
        # 12001 characters across the step, the names and the values.
        {
            "step": "s" * 200,
            "fields": [
                {"name": "a", "value": "x" * 4000},
                {"name": "b", "value": "x" * 4000},
                {"name": "c", "value": "x" * 3798},
            ],
        },
        {"extra": "no"},
    ],
    ids=[
        "21-fields",
        "65-char-name",
        "empty-name",
        "4001-char-value",
        "201-char-step",
        "12001-total",
        "unknown-key",
    ],
)
def test_an_oversized_working_context_is_refused(context: dict[str, object]) -> None:
    client, service = _client()
    with client:
        refused = client.post(
            "/api/v1/activities/41/coach/messages", json={"text": "hola", "context": context}
        )

    assert refused.status_code == 422
    assert service.sent == []


def test_a_working_context_of_exactly_12000_characters_is_accepted() -> None:
    fields = [
        {"name": "a", "value": "x" * 4000},
        {"name": "b", "value": "x" * 4000},
        {"name": "c", "value": "x" * 3797},
    ]
    client, service = _client()
    with client:
        sent = client.post(
            "/api/v1/activities/41/coach/messages",
            json={"text": "hola", "context": {"step": "s" * 200, "fields": fields}},
        )

    assert sent.status_code == 200 and service.sent == ["hola"]


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["planner", "interviewer", "none", "reviewer"])
async def test_an_uncommitted_block_of_any_role_is_coachable_with_the_same_next_step(
    role: str,
) -> None:
    service = CoachThreadService(cast(Any, None), coach=CoachService(None, model="m"))
    definition = TaskDefinition(
        stable_id="x",
        objective="o",
        allowed_ai_role=role,
        output_contract={"items": [], "procedure": [{"phase": "sealed_final_mock"}]},
        pass_contract={"items": []},
    )
    activity = ActivityInstance(id=41, state="ready", output_committed_at=None)

    response = await service._response(_Loaded(activity, definition, None))

    assert response.coaching_allowed
    assert response.next_step == (
        "Write your independent attempt; ask the coach for a hint only when stuck."
    )


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
