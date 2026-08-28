from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.learning.enums import ActivityState, IncompleteClassification
from tamforge_backend.learning.routes import get_activity_service
from tamforge_backend.learning.schemas import ActivityResponse, TimerResponse
from tamforge_backend.learning.service import ActivityConflict
from tamforge_backend.main import create_app

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubActivityService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.conflict = False

    def _response(self, *, state: ActivityState, version: int) -> ActivityResponse:
        return ActivityResponse(
            id=7,
            study_day_id=3,
            state=state,
            optimistic_version=version,
            classification=IncompleteClassification.REQUIRED,
            stronger_evidence_id=None,
            activity_focused_seconds=12,
            day_focused_minutes=1,
            hard_stop_recommended=False,
            open_timer=(
                TimerResponse(
                    id=9,
                    started_at=datetime(2026, 8, 27, 12, tzinfo=UTC),
                    last_heartbeat_at=datetime(2026, 8, 27, 12, 0, 12, tzinfo=UTC),
                    counted_seconds=12,
                    last_client_sequence=1,
                )
                if state is ActivityState.ACTIVE
                else None
            ),
        )

    async def get_activity(self, **values: object) -> ActivityResponse:
        self.calls.append(("get", values))
        return self._response(state=ActivityState.READY, version=1)

    async def start(self, **values: object) -> ActivityResponse:
        self.calls.append(("start", values))
        if self.conflict:
            raise ActivityConflict("internal state must not leak")
        return self._response(state=ActivityState.ACTIVE, version=2)

    async def pause(self, **values: object) -> ActivityResponse:
        self.calls.append(("pause", values))
        return self._response(state=ActivityState.PAUSED, version=3)

    async def resume(self, **values: object) -> ActivityResponse:
        self.calls.append(("resume", values))
        return self._response(state=ActivityState.ACTIVE, version=4)

    async def heartbeat(self, **values: object) -> ActivityResponse:
        self.calls.append(("heartbeat", values))
        return self._response(state=ActivityState.ACTIVE, version=2)

    async def classify_incomplete(self, **values: object) -> ActivityResponse:
        self.calls.append(("classify-incomplete", values))
        return self._response(state=ActivityState.INCOMPLETE, version=3)


def _client() -> tuple[TestClient, StubActivityService]:
    settings = Settings(
        environment="test",
        github_user_id=102269369,
        cors_origins=["https://app.example.test"],
        secure_cookies=False,
        _env_file=None,
    )
    app = create_app(settings)
    service = StubActivityService()
    app.dependency_overrides[get_activity_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_authenticated_activity_commands_forward_only_bounded_contracts() -> None:
    client, service = _client()
    with client:
        fetched = client.get("/api/v1/activities/7")
        started = client.post(
            "/api/v1/activities/7/start",
            json={"expected_version": 1},
            headers={"Idempotency-Key": "start-7"},
        )
        heartbeat = client.post(
            "/api/v1/activities/7/heartbeat",
            json={"expected_version": 2, "client_sequence": 1},
            headers={"Idempotency-Key": "heartbeat-7-1"},
        )
        paused = client.post(
            "/api/v1/activities/7/pause",
            json={"expected_version": 2, "client_sequence": 2},
            headers={"Idempotency-Key": "pause-7"},
        )
        resumed = client.post(
            "/api/v1/activities/7/resume",
            json={"expected_version": 3},
            headers={"Idempotency-Key": "resume-7"},
        )
        incomplete = client.post(
            "/api/v1/activities/7/classify-incomplete",
            json={"expected_version": 4, "classification": "useful"},
            headers={"Idempotency-Key": "incomplete-7"},
        )

    assert [
        response.status_code
        for response in (fetched, started, heartbeat, paused, resumed, incomplete)
    ] == [200] * 6
    assert all(
        response.headers["cache-control"] == "no-store"
        for response in (fetched, started, heartbeat, paused, resumed, incomplete)
    )
    assert service.calls == [
        ("get", {"owner_id": 1, "activity_id": 7}),
        (
            "start",
            {
                "owner_id": 1,
                "activity_id": 7,
                "expected_version": 1,
                "idempotency_key": "start-7",
            },
        ),
        (
            "heartbeat",
            {
                "owner_id": 1,
                "activity_id": 7,
                "expected_version": 2,
                "client_sequence": 1,
                "idempotency_key": "heartbeat-7-1",
            },
        ),
        (
            "pause",
            {
                "owner_id": 1,
                "activity_id": 7,
                "expected_version": 2,
                "client_sequence": 2,
                "idempotency_key": "pause-7",
            },
        ),
        (
            "resume",
            {
                "owner_id": 1,
                "activity_id": 7,
                "expected_version": 3,
                "idempotency_key": "resume-7",
            },
        ),
        (
            "classify-incomplete",
            {
                "owner_id": 1,
                "activity_id": 7,
                "expected_version": 4,
                "classification": IncompleteClassification.USEFUL,
                "stronger_evidence_id": None,
                "idempotency_key": "incomplete-7",
            },
        ),
    ]


def test_activity_command_errors_are_closed_and_do_not_leak_internal_detail() -> None:
    client, service = _client()
    service.conflict = True
    with client:
        response = client.post(
            "/api/v1/activities/7/start",
            json={"expected_version": 1},
            headers={"Idempotency-Key": "start-conflict"},
        )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "activity_state_conflict"
    assert "internal state" not in response.text


def test_activity_command_schemas_reject_unbounded_or_ambiguous_input() -> None:
    client, service = _client()
    with client:
        unknown = client.post(
            "/api/v1/activities/7/start",
            json={"expected_version": 1, "unexpected": True},
            headers={"Idempotency-Key": "start-extra"},
        )
        invalid_superseded = client.post(
            "/api/v1/activities/7/classify-incomplete",
            json={"expected_version": 2, "classification": "superseded"},
            headers={"Idempotency-Key": "incomplete-invalid"},
        )

    assert unknown.status_code == 422
    assert invalid_superseded.status_code == 422
    assert service.calls == []
