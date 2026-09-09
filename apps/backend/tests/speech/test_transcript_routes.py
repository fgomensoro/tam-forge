from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import (
    get_auth_service,
    get_bearer_authenticated_owner,
)
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.speech.contracts import TranscriptConflict, TranscriptNotFound
from tamforge_backend.speech.routes import get_transcript_service
from tamforge_backend.speech.schemas import (
    TranscriptCorrectionCommand,
    TranscriptCorrectionResponse,
    TranscriptPage,
    TranscriptResponse,
    TranscriptSubmitCommand,
)

RECORDING_ID = UUID("11111111-1111-4111-8111-111111111111")
CREATED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def transcript_payload(
    *, track: str = "microphone", text: str = "hello there", model_sha256: str | None = None
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "track": track,
        "segments": [
            {
                "text": text,
                "start_ms": 0,
                "end_ms": 900,
                "words": [
                    {"text": text.split()[0], "start_ms": 0, "end_ms": 400, "probability": 0.98}
                ],
            }
        ],
        "model_identity": {
            "runtime_version": "b4938",
            "model_filename": "ggml-base.en-q5_1.bin",
            "model_sha256": model_sha256 or "a" * 64,
            "metal_requested": True,
            "used_builtin_vad": False,
            "language": "en",
        },
        "derivation": {
            "derivation_version": "tamforge-asr16k-v1",
            "source_sample_rate": 48000,
            "source_channel_count": 1,
            "source_sample_count": 2880000,
            "output_sample_rate": 16000,
            "output_sample_count": 960000,
            "zero_filled_gaps": [],
            "source_pcm_sha256": "b" * 64,
            "derived_pcm_sha256": "c" * 64,
            "quality": {
                "version": "audio-quality-v1",
                "sample_rate": 48000,
                "channel_count": 1,
                "source_sample_count": 2880000,
                "duration_seconds": 60.0,
                "peak_absolute": 21000,
                "all_silence": False,
                "clipped_ratio": 0.0,
                "dc_offset": 0.0,
                "channel_imbalance_decibels": None,
                "discontinuity_count": 0,
                "unavailable_dimensions": [],
            },
        },
    }


def correction_payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": 1,
        "segment_index": 0,
        "word_start_index": 0,
        "word_end_index": 1,
        "original_text": "helo",
        "corrected_text": "hello",
        "reason": "misheard_term",
    }
    body.update(overrides)
    return body


class StubTranscriptService:
    """Records what it was called with; scenario subclasses add behavior.

    Mirrors `StubRecordingService` in `tests/recordings/test_session_routes.py`:
    a route test only needs to see that the route resolved the authenticated
    owner and wired the request through, not exercise real persistence.
    """

    def __init__(self) -> None:
        self.owner_ids: list[int] = []

    async def submit(
        self, *, owner_id: int, recording_id: UUID, command: TranscriptSubmitCommand
    ) -> TranscriptResponse:
        self.owner_ids.append(owner_id)
        return TranscriptResponse(
            transcript_id=1,
            recording_id=recording_id,
            track=command.track,
            content_hash="a" * 64,
            created_at=CREATED_AT,
            replayed=False,
            corrections=(),
        )

    async def list_for_recording(self, *, owner_id: int, recording_id: UUID) -> TranscriptPage:
        self.owner_ids.append(owner_id)
        raise AssertionError("not used in this route test")

    async def add_correction(
        self,
        *,
        owner_id: int,
        recording_id: UUID,
        track: str,
        command: TranscriptCorrectionCommand,
    ) -> TranscriptCorrectionResponse:
        self.owner_ids.append(owner_id)
        raise AssertionError("not used in this route test")


class ConflictTranscriptService(StubTranscriptService):
    """Stands in for a recording whose audio is not durable on the server yet."""

    async def submit(
        self, *, owner_id: int, recording_id: UUID, command: TranscriptSubmitCommand
    ) -> TranscriptResponse:
        self.owner_ids.append(owner_id)
        raise TranscriptConflict()


class IdempotentTranscriptService(StubTranscriptService):
    """A minimal in-memory stand-in for the repository's own content-hash replay
    and conflict rule: identical resubmission on a track returns the stored
    result, a differing one on the same track conflicts. Real persistence and
    the actual race handling are Task 3's repository tests; this only proves
    the route surfaces whatever the service decides as 201-replayed or 409.
    """

    def __init__(self) -> None:
        super().__init__()
        self._stored: dict[tuple[UUID, str], tuple[dict[str, object], TranscriptResponse]] = {}
        self._next_id = 1

    async def submit(
        self, *, owner_id: int, recording_id: UUID, command: TranscriptSubmitCommand
    ) -> TranscriptResponse:
        self.owner_ids.append(owner_id)
        content = command.model_dump(mode="json")
        key = (recording_id, command.track)
        existing = self._stored.get(key)
        if existing is not None:
            existing_content, existing_response = existing
            if existing_content != content:
                raise TranscriptConflict()
            return existing_response.model_copy(update={"replayed": True})
        response = TranscriptResponse(
            transcript_id=self._next_id,
            recording_id=recording_id,
            track=command.track,
            content_hash="a" * 64,
            created_at=CREATED_AT,
            replayed=False,
            corrections=(),
        )
        self._next_id += 1
        self._stored[key] = (content, response)
        return response


class ListingTranscriptService(StubTranscriptService):
    """Returns a distinct canned page per owner id to prove owner scoping."""

    def __init__(self) -> None:
        super().__init__()
        self.pages: dict[int, TranscriptPage] = {}

    async def list_for_recording(self, *, owner_id: int, recording_id: UUID) -> TranscriptPage:
        self.owner_ids.append(owner_id)
        return self.pages.get(owner_id, TranscriptPage(items=()))


class CorrectionTranscriptService(StubTranscriptService):
    def __init__(self) -> None:
        super().__init__()
        self.seen_tracks: list[str] = []
        self.missing_track: str | None = None
        self.at_capacity = False

    async def add_correction(
        self,
        *,
        owner_id: int,
        recording_id: UUID,
        track: str,
        command: TranscriptCorrectionCommand,
    ) -> TranscriptCorrectionResponse:
        self.owner_ids.append(owner_id)
        self.seen_tracks.append(track)
        if track == self.missing_track:
            raise TranscriptNotFound()
        if self.at_capacity:
            raise TranscriptConflict()
        return TranscriptCorrectionResponse(
            correction_id=1,
            transcript_id=1,
            segment_index=command.segment_index,
            word_start_index=command.word_start_index,
            word_end_index=command.word_end_index,
            original_text=command.original_text,
            corrected_text=command.corrected_text,
            reason=command.reason,
            created_at=CREATED_AT,
            replayed=False,
        )


def owner(owner_id: int = 7) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=owner_id,
        github_user_id=102269369,
        github_login="fgomensoro",
        session_id=1,
        csrf_hash=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method="bearer",
    )


class StubBearerAuthService:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def authenticate_bearer(self, token: str) -> AuthenticatedOwner:
        self.tokens.append(token)
        return owner()


def client_for(service: StubTranscriptService, *, identity: AuthenticatedOwner | None = None):
    app = create_app(
        Settings(environment="test", github_user_id=102269369, secure_cookies=False, _env_file=None)
    )
    app.dependency_overrides[get_bearer_authenticated_owner] = lambda: identity or owner()
    app.dependency_overrides[get_transcript_service] = lambda: service
    return TestClient(app)


def client_with_real_bearer_dependency(service: StubTranscriptService):
    app = create_app(
        Settings(environment="test", github_user_id=102269369, secure_cookies=False, _env_file=None)
    )
    auth = StubBearerAuthService()
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_transcript_service] = lambda: service
    return TestClient(app), auth


def test_submit_transcript_returns_201_and_scopes_the_authenticated_owner() -> None:
    service = StubTranscriptService()
    client = client_for(service)
    with client:
        response = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            json=transcript_payload(),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "transcript-1"},
        )

    assert response.status_code == 201
    assert service.owner_ids == [7]
    body = response.json()
    assert body["recording_id"] == str(RECORDING_ID)
    assert body["track"] == "microphone"
    assert body["replayed"] is False
    assert response.headers["cache-control"] == "no-store"


def test_submit_transcript_for_a_recording_without_durable_audio_returns_409() -> None:
    client = client_for(ConflictTranscriptService())
    with client:
        response = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            json=transcript_payload(),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "transcript-1"},
        )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "transcript_conflict"
    assert response.headers["cache-control"] == "no-store"


def test_identical_resubmission_with_the_same_idempotency_key_replays_the_stored_result() -> None:
    service = IdempotentTranscriptService()
    client = client_for(service)
    payload = transcript_payload()
    headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "transcript-1"}
    with client:
        first = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts", json=payload, headers=headers
        )
        second = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts", json=payload, headers=headers
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["replayed"] is False
    assert second.json()["replayed"] is True
    assert first.json()["transcript_id"] == second.json()["transcript_id"]


def test_differing_resubmission_on_the_same_track_returns_409() -> None:
    service = IdempotentTranscriptService()
    client = client_for(service)
    headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "transcript-1"}
    with client:
        first = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            json=transcript_payload(),
            headers=headers,
        )
        second = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            json=transcript_payload(model_sha256="f" * 64),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "transcript-2"},
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "transcript_conflict"


def test_submit_transcript_without_bearer_token_returns_401() -> None:
    client, auth = client_with_real_bearer_dependency(StubTranscriptService())
    with client:
        response = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            json=transcript_payload(),
            headers={"Idempotency-Key": "transcript-1"},
        )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "unauthenticated"
    assert auth.tokens == []


def test_get_transcripts_returns_only_the_calling_owners_page() -> None:
    service = ListingTranscriptService()
    owner_a_page = TranscriptPage(
        items=(
            TranscriptResponse(
                transcript_id=1,
                recording_id=RECORDING_ID,
                track="microphone",
                content_hash="a" * 64,
                created_at=CREATED_AT,
                replayed=False,
                corrections=(),
            ),
        )
    )
    owner_b_page = TranscriptPage(items=())
    service.pages[7] = owner_a_page
    service.pages[9] = owner_b_page

    with client_for(service, identity=owner(7)) as client:
        response_a = client.get(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            headers={"Authorization": "Bearer test-token"},
        )
    with client_for(service, identity=owner(9)) as client:
        response_b = client.get(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            headers={"Authorization": "Bearer test-token"},
        )

    assert response_a.status_code == 200
    assert len(response_a.json()["items"]) == 1
    assert response_b.status_code == 200
    assert response_b.json()["items"] == []
    assert service.owner_ids == [7, 9]
    assert response_a.headers["cache-control"] == "no-store"


def test_submit_correction_returns_201_with_the_path_track() -> None:
    service = CorrectionTranscriptService()
    client = client_for(service)
    with client:
        response = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts/microphone/corrections",
            json=correction_payload(),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "correction-1"},
        )

    assert response.status_code == 201
    assert service.seen_tracks == ["microphone"]
    assert response.json()["corrected_text"] == "hello"
    assert response.headers["cache-control"] == "no-store"


def test_submit_correction_for_a_missing_transcript_track_returns_404() -> None:
    service = CorrectionTranscriptService()
    service.missing_track = "system_audio"
    client = client_for(service)
    with client:
        response = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts/system_audio/corrections",
            json=correction_payload(),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "correction-1"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "transcript_not_found"


def test_transcript_text_never_reaches_a_response_body() -> None:
    marker = "zzsecretzzmarkerzz"
    client = client_for(StubTranscriptService())
    with client:
        success = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            json=transcript_payload(text=marker),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "transcript-1"},
        )
        invalid_payload = transcript_payload(text=marker)
        invalid_payload["segments"][0]["end_ms"] = -1  # fails the schema's Milliseconds bound
        invalid = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            json=invalid_payload,
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "transcript-2"},
        )

    conflict_client = client_for(ConflictTranscriptService())
    with conflict_client:
        conflict = conflict_client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts",
            json=transcript_payload(text=marker),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "transcript-3"},
        )

    assert success.status_code == 201
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_recording_request"
    assert conflict.status_code == 409
    for response in (success, invalid, conflict):
        assert marker not in response.text


def test_submit_correction_for_a_transcript_at_the_correction_cap_returns_409() -> None:
    """A transcript with no room left for another correction is a conflict with
    durable state, not a malformed request and not an oversized body: the
    correction itself passed every schema bound to get here. It has to reach the
    client as the same problem+json every other transcript conflict does.
    """
    service = CorrectionTranscriptService()
    service.at_capacity = True
    client = client_for(service)
    with client:
        response = client.post(
            f"/api/v1/recordings/{RECORDING_ID}/transcripts/microphone/corrections",
            json=correction_payload(),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "correction-1"},
        )

    assert response.status_code == 409
    assert response.json()["code"] == "transcript_conflict"


def test_the_corrections_route_declares_its_conflict_response() -> None:
    """The native client is generated from this document, so a status the route
    can actually return has to be declared here or the generated client has no
    case for it. Corrections had no 409 to declare until the cap gave them one.
    """
    app = create_app(
        Settings(environment="test", github_user_id=102269369, secure_cookies=False, _env_file=None)
    )
    path = "/api/v1/recordings/{recording_id}/transcripts/{track}/corrections"

    responses = app.openapi()["paths"][path]["post"]["responses"]

    assert "409" in responses
