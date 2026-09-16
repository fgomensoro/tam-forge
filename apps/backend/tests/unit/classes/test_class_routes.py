from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.classes.routes import get_english_class_service
from tamforge_backend.classes.schemas import (
    ClassRecordingSummary,
    EnglishClassCommand,
    EnglishClassPage,
    EnglishClassResponse,
)
from tamforge_backend.classes.service import ClassConflict, ClassNotFound
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
RECORDING = UUID("22222222-2222-4222-8222-222222222222")


def _record(
    class_id: int, command: EnglishClassCommand, attached: bool = False
) -> EnglishClassResponse:
    return EnglishClassResponse(
        id=class_id,
        teacher=command.teacher,
        starts_at=command.starts_at,
        expected_duration_minutes=command.expected_duration_minutes,
        notes=command.notes,
        skill_slug="tam_english",
        recordings=(
            (
                ClassRecordingSummary(
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
        self.commands: list[EnglishClassCommand] = []

    async def list(self, *, owner_id: int) -> EnglishClassPage:
        return EnglishClassPage(items=())

    async def get(self, *, owner_id: int, class_id: int) -> EnglishClassResponse:
        if self.error is not None:
            raise self.error
        return _record(class_id, self.commands[-1])

    async def create(self, *, owner_id: int, command: EnglishClassCommand) -> EnglishClassResponse:
        self.commands.append(command)
        return _record(3, command)

    async def update(
        self, *, owner_id: int, class_id: int, command: EnglishClassCommand
    ) -> EnglishClassResponse:
        self.commands.append(command)
        return _record(class_id, command)

    async def attach_recording(
        self, *, owner_id: int, class_id: int, recording_id: UUID
    ) -> EnglishClassResponse:
        if self.error is not None:
            raise self.error
        assert recording_id == RECORDING
        return _record(class_id, self.commands[-1], attached=True)


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
    app.dependency_overrides[get_english_class_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


BODY = {
    "teacher": "Maria",
    "starts_at": "2026-09-18T18:00:00Z",
    "expected_duration_minutes": 60,
    "notes": "Conditionals and pacing.",
}


def test_create_edit_attach_and_list_round_trip() -> None:
    client, service = _client()
    with client:
        created = client.post("/api/v1/english-classes", json=BODY)
        edited = client.put("/api/v1/english-classes/3", json={**BODY, "notes": "Pacing only."})
        attached = client.post(
            "/api/v1/english-classes/3/recordings", json={"recording_id": str(RECORDING)}
        )
        listed = client.get("/api/v1/english-classes")
        invalid = client.post("/api/v1/english-classes", json={**BODY, "teacher": ""})

    assert created.status_code == 201
    assert (
        created.json()["kind"] == "english_class" and created.json()["skill_slug"] == "tam_english"
    )
    assert created.headers["cache-control"] == "no-store"
    assert edited.status_code == 200 and edited.json()["notes"] == "Pacing only."
    assert attached.status_code == 200
    assert attached.json()["recordings"][0]["recording_id"] == str(RECORDING)
    assert listed.status_code == 200 and listed.json() == {"items": []}
    assert invalid.status_code == 422


def test_problems_map_to_closed_codes() -> None:
    client, service = _client()
    with client:
        client.post("/api/v1/english-classes", json=BODY)
        service.error = ClassNotFound("none")
        missing = client.get("/api/v1/english-classes/9")
        service.error = ClassConflict("other")
        conflict = client.post(
            "/api/v1/english-classes/3/recordings", json={"recording_id": str(RECORDING)}
        )

    assert missing.status_code == 404 and missing.json()["code"] == "class_not_found"
    assert conflict.status_code == 409 and conflict.json()["code"] == "class_conflict"
