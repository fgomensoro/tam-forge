from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.interviews.routes import get_interview_service
from tamforge_backend.interviews.schemas import (
    InterviewCommand,
    InterviewPage,
    InterviewRecordingSummary,
    InterviewResponse,
)
from tamforge_backend.interviews.service import InterviewConflict, InterviewNotFound
from tamforge_backend.main import create_app

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)
RECORDING = UUID("11111111-1111-4111-8111-111111111111")


def _record(
    interview_id: int, command: InterviewCommand, attached: bool = False
) -> InterviewResponse:
    return InterviewResponse(
        id=interview_id,
        company=command.company,
        role=command.role,
        stage=command.stage,
        starts_at=command.starts_at,
        expected_duration_minutes=command.expected_duration_minutes,
        status=command.status,
        privacy_permission_code=command.privacy_permission_code,
        recordings=(
            (
                InterviewRecordingSummary(
                    recording_id=RECORDING,
                    state="stored",
                    started_at=None,
                    transcript_lineage_accepted=True,
                ),
            )
            if attached
            else ()
        ),
        created_at=datetime(2026, 9, 16, tzinfo=UTC),
        updated_at=datetime(2026, 9, 16, tzinfo=UTC),
    )


class StubService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.commands: list[InterviewCommand] = []
        self.attached: list[tuple[int, UUID]] = []

    async def list(self, *, owner_id: int) -> InterviewPage:
        assert owner_id == 1
        return InterviewPage(items=())

    async def get(self, *, owner_id: int, interview_id: int) -> InterviewResponse:
        if self.error is not None:
            raise self.error
        return _record(interview_id, self.commands[-1])

    async def create(self, *, owner_id: int, command: InterviewCommand) -> InterviewResponse:
        self.commands.append(command)
        return _record(5, command)

    async def update(
        self, *, owner_id: int, interview_id: int, command: InterviewCommand
    ) -> InterviewResponse:
        self.commands.append(command)
        return _record(interview_id, command)

    async def attach_recording(
        self, *, owner_id: int, interview_id: int, recording_id: UUID
    ) -> InterviewResponse:
        if self.error is not None:
            raise self.error
        self.attached.append((interview_id, recording_id))
        return _record(interview_id, self.commands[-1], attached=True)


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
    app.dependency_overrides[get_interview_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


BODY = {
    "company": "Acme",
    "role": "TAM",
    "stage": "screen",
    "starts_at": "2026-09-20T15:00:00Z",
    "expected_duration_minutes": 45,
    "status": "scheduled",
    "privacy_permission_code": "permission_granted",
}


def test_create_edit_attach_and_read_round_trip_without_caching() -> None:
    client, service = _client()
    with client:
        created = client.post("/api/v1/interviews", json=BODY)
        edited = client.put("/api/v1/interviews/5", json={**BODY, "stage": "panel"})
        attached = client.post(
            "/api/v1/interviews/5/recordings", json={"recording_id": str(RECORDING)}
        )
        listed = client.get("/api/v1/interviews")
        invalid = client.post("/api/v1/interviews", json={**BODY, "status": "ghosted"})

    assert created.status_code == 201 and created.json()["id"] == 5
    assert created.headers["cache-control"] == "no-store"
    assert edited.status_code == 200 and edited.json()["stage"] == "panel"
    assert attached.status_code == 200
    assert attached.json()["recordings"][0]["recording_id"] == str(RECORDING)
    assert service.attached == [(5, RECORDING)]
    assert listed.status_code == 200 and listed.json() == {"items": []}
    assert invalid.status_code == 422


def test_problems_map_to_closed_codes() -> None:
    client, service = _client()
    with client:
        client.post("/api/v1/interviews", json=BODY)
        service.error = InterviewNotFound("none")
        missing = client.get("/api/v1/interviews/9")
        service.error = InterviewConflict("other")
        conflict = client.post(
            "/api/v1/interviews/5/recordings", json={"recording_id": str(RECORDING)}
        )

    assert missing.status_code == 404 and missing.json()["code"] == "interview_not_found"
    assert conflict.status_code == 409 and conflict.json()["code"] == "interview_conflict"
