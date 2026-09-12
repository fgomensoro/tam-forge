from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.notes.routes import get_study_note_service
from tamforge_backend.notes.schemas import (
    StudyNoteContent,
    StudyNoteResponse,
    StudyNoteSearchResponse,
    StudyNoteSummary,
)
from tamforge_backend.notes.service import NoteConflict, NoteNotFound, NotesUnavailable

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


def _note(status: str = "draft", title: str = "Webhooks") -> StudyNoteResponse:
    return StudyNoteResponse(
        id=5,
        activity_id=41,
        stable_id="p1-w01-d01-roadmap",
        local_date=date(2026, 9, 12),
        status=status,  # type: ignore[arg-type]
        drafted_by="coach",
        assistance="coached",
        assessment_status="self_review_complete",
        title=title,
        rule="A 200 confirms acceptance.",
        flashcards=[{"question": "What does a 200 confirm?", "answer": "Acceptance."}],  # type: ignore[list-item]
        artifact_id=9 if status == "approved" else None,
        content_sha256="ab" * 32 if status == "approved" else None,
        updated_at=datetime(2026, 9, 12, tzinfo=UTC),
        approved_at=datetime(2026, 9, 12, tzinfo=UTC) if status == "approved" else None,
    )


class StubService:
    def __init__(self) -> None:
        self.saved: list[StudyNoteContent] = []
        self.error: Exception | None = None

    async def get(self, *, owner_id: int, activity_id: int) -> StudyNoteResponse:
        assert owner_id == 1 and activity_id == 41
        if self.error is not None:
            raise self.error
        return _note()

    async def draft(self, *, owner_id: int, activity_id: int) -> StudyNoteResponse:
        assert owner_id == 1 and activity_id == 41
        if self.error is not None:
            raise self.error
        return _note()

    async def save(
        self, *, owner_id: int, activity_id: int, content: StudyNoteContent
    ) -> StudyNoteResponse:
        assert owner_id == 1 and activity_id == 41
        if self.error is not None:
            raise self.error
        self.saved.append(content)
        return _note(title=content.title)

    async def approve(self, *, owner_id: int, activity_id: int) -> StudyNoteResponse:
        assert owner_id == 1 and activity_id == 41
        if self.error is not None:
            raise self.error
        return _note(status="approved")

    async def search(self, *, owner_id: int, query: str) -> StudyNoteSearchResponse:
        assert owner_id == 1
        return StudyNoteSearchResponse(
            query=query,
            items=[
                StudyNoteSummary(
                    id=5,
                    activity_id=41,
                    stable_id="p1-w01-d01-roadmap",
                    local_date=date(2026, 9, 12),
                    title="Webhooks",
                    status="approved",
                    assistance="coached",
                    flashcard_count=1,
                    updated_at=datetime(2026, 9, 12, tzinfo=UTC),
                )
            ],
        )

    async def export(self, *, owner_id: int, since: date | None, until: date | None) -> bytes:
        assert owner_id == 1
        return b"PK\x05\x06" + bytes(18) + f"{since}|{until}".encode()


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
    app.dependency_overrides[get_study_note_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_note_read_draft_save_approve_search_and_export_round_trip() -> None:
    client, service = _client()
    with client:
        read = client.get("/api/v1/activities/41/note")
        drafted = client.post("/api/v1/activities/41/note/draft")
        saved = client.put(
            "/api/v1/activities/41/note",
            json={"title": "Webhooks, corrected", "rule": "A 200 confirms acceptance."},
        )
        approved = client.post("/api/v1/activities/41/note/approve")
        found = client.get("/api/v1/notes", params={"query": "webhook"})
        exported = client.get("/api/v1/notes/export", params={"since": "2026-09-01"})

    assert read.status_code == 200 and read.json()["status"] == "draft"
    assert read.headers["cache-control"] == "no-store"
    assert drafted.status_code == 200 and drafted.json()["drafted_by"] == "coach"
    assert saved.status_code == 200 and saved.json()["title"] == "Webhooks, corrected"
    assert service.saved[0].rule == "A 200 confirms acceptance."
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved" and approved.json()["artifact_id"] == 9
    assert found.status_code == 200 and found.json()["items"][0]["flashcard_count"] == 1
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert exported.content.endswith(b"2026-09-01|None")


def test_problems_map_to_closed_codes() -> None:
    client, service = _client()
    with client:
        service.error = NoteNotFound("none")
        missing = client.get("/api/v1/activities/41/note")
        service.error = NoteConflict("frozen")
        conflict = client.put("/api/v1/activities/41/note", json={"title": "x"})
        service.error = NotesUnavailable("down")
        unavailable = client.post("/api/v1/activities/41/note/draft")
        service.error = None
        invalid = client.put("/api/v1/activities/41/note", json={"title": ""})

    assert missing.status_code == 404 and missing.json()["code"] == "note_not_found"
    assert conflict.status_code == 409 and conflict.json()["code"] == "note_conflict"
    assert unavailable.status_code == 503 and unavailable.json()["code"] == "notes_unavailable"
    assert invalid.status_code == 422
