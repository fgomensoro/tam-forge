from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.interviews.routes import get_interview_service, get_reference_service
from tamforge_backend.interviews.schemas import (
    InterviewTranscriptCommand,
    InterviewTranscriptResponse,
    ReferenceEntryResponse,
    ReferenceImportCommand,
    ReferenceImportResponse,
    ReferencePage,
    TranscriptTurnResponse,
)
from tamforge_backend.interviews.service import InterviewInvalid, InterviewNotFound
from tamforge_backend.main import create_app

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)


def _transcript(interview_id: int) -> InterviewTranscriptResponse:
    return InterviewTranscriptResponse(
        interview_id=interview_id,
        analysis_kind="transcript_only",
        analysis_version="transcript-only-v1",
        turns=(TranscriptTurnResponse(speaker="learner", label="Frank", text="Sure."),),
        learner_words=1,
        other_words=0,
        learner_turns=1,
        other_turns=0,
        learner_word_share=1.0,
        longest_learner_turn_words=1,
        excluded_findings=("pronunciation", "fluency", "pace", "pauses", "fillers"),
        created_at=NOW,
    )


class StubInterviews:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.commands: list[tuple[int, InterviewTranscriptCommand]] = []

    async def attach_transcript(
        self, *, owner_id: int, interview_id: int, command: InterviewTranscriptCommand
    ) -> InterviewTranscriptResponse:
        if self.error is not None:
            raise self.error
        self.commands.append((interview_id, command))
        return _transcript(interview_id)

    async def transcript(self, *, owner_id: int, interview_id: int) -> InterviewTranscriptResponse:
        if self.error is not None:
            raise self.error
        return _transcript(interview_id)


class StubReference:
    def __init__(self) -> None:
        self.commands: list[ReferenceImportCommand] = []
        self.kinds: list[str | None] = []

    async def import_markdown(
        self, *, owner_id: int, command: ReferenceImportCommand
    ) -> ReferenceImportResponse:
        self.commands.append(command)
        entry = ReferenceEntryResponse(
            id=1,
            kind=command.kind,
            document_title=command.title,
            heading="Tell me about yourself",
            body="Eight years in payments.",
            readiness_label="ready",
            readiness_verified=False,
            created_at=NOW,
        )
        return ReferenceImportResponse(kind=command.kind, created=1, existing=0, entries=(entry,))

    async def list(self, *, owner_id: int, kind: str | None = None) -> ReferencePage:
        self.kinds.append(kind)
        return ReferencePage(items=())


def _client() -> tuple[TestClient, StubInterviews, StubReference]:
    app = create_app(
        Settings(
            environment="test",
            github_user_id=102269369,
            cors_origins=["https://app.example.test"],
            secure_cookies=False,
            _env_file=None,
        )
    )
    interviews, reference = StubInterviews(), StubReference()
    app.dependency_overrides[get_interview_service] = lambda: interviews
    app.dependency_overrides[get_reference_service] = lambda: reference
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), interviews, reference


def test_a_transcript_only_interview_is_labeled_and_never_claims_speech_findings() -> None:
    client, interviews, _ = _client()
    with client:
        attached = client.post(
            "/api/v1/interviews/7/transcript",
            json={"text": "Interviewer: hi\nFrank: Sure.", "learner_labels": ["Frank"]},
        )
        read = client.get("/api/v1/interviews/7/transcript")
        blank = client.post("/api/v1/interviews/7/transcript", json={"text": ""})

    assert attached.status_code == 201, attached.text
    assert attached.headers["cache-control"] == "no-store"
    payload = attached.json()
    assert payload["analysis_kind"] == "transcript_only"
    assert "pronunciation" in payload["excluded_findings"]
    assert "fluency" in payload["excluded_findings"]
    assert read.status_code == 200 and read.json()["turns"][0]["label"] == "Frank"
    assert blank.status_code == 422
    assert interviews.commands[0][1].learner_labels == ("Frank",)


def test_reference_material_imports_with_unverified_readiness_and_lists_by_kind() -> None:
    client, _, reference = _client()
    with client:
        imported = client.post(
            "/api/v1/reference-material",
            json={"kind": "answer_bank", "title": "Answer bank", "markdown": "## Q\nA"},
        )
        listed = client.get("/api/v1/reference-material?kind=story_catalog")
        bad_kind = client.get("/api/v1/reference-material?kind=recipes")

    assert imported.status_code == 201, imported.text
    entry = imported.json()["entries"][0]
    assert entry["readiness_label"] == "ready" and entry["readiness_verified"] is False
    assert listed.status_code == 200 and reference.kinds == ["story_catalog"]
    assert bad_kind.status_code == 422


def test_problems_are_closed() -> None:
    client, interviews, _ = _client()
    interviews.error = InterviewNotFound("internal")
    with client:
        missing = client.get("/api/v1/interviews/7/transcript")
        interviews.error = InterviewInvalid("internal")
        invalid = client.post("/api/v1/interviews/7/transcript", json={"text": "x"})

    assert missing.status_code == 404 and missing.json()["code"] == "interview_not_found"
    assert invalid.status_code == 422 and invalid.json()["code"] == "interview_invalid"
    assert "internal" not in missing.text + invalid.text
