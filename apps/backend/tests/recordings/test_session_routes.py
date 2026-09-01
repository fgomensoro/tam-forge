from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.recordings.routes import get_recording_service
from tamforge_backend.recordings.schemas import (
    RecordingCreateCommand,
    RecordingCreateResponse,
    RecordingPartReceipt,
    RecordingPartUploadMetadata,
    RecordingSealCommand,
    RecordingSealResponse,
    RecordingStatusResponse,
)

RECORDING_ID = UUID("11111111-1111-4111-8111-111111111111")
MICROPHONE_ID = UUID("22222222-2222-4222-8222-222222222222")
SYSTEM_ID = UUID("33333333-3333-4333-8333-333333333333")


class StubRecordingService:
    def __init__(self) -> None:
        self.part_key: bytes | None = None
        self.owner_ids: list[int] = []

    async def create(
        self, *, owner_id: int, command: RecordingCreateCommand, idempotency_key: str
    ) -> RecordingCreateResponse:
        self.owner_ids.append(owner_id)
        assert command.recording_id == RECORDING_ID
        assert idempotency_key == "create-1"
        return RecordingCreateResponse(
            recording_id=command.recording_id, state="reserved", replayed=False
        )

    async def upload_part(
        self,
        *,
        owner_id: int,
        metadata: RecordingPartUploadMetadata,
        part_key: bytes,
        ciphertext: bytes,
        idempotency_key: str,
    ) -> RecordingPartReceipt:
        self.owner_ids.append(owner_id)
        self.part_key = part_key
        assert ciphertext == b"c" * 32
        assert idempotency_key == "part-1"
        return RecordingPartReceipt(
            recording_id=metadata.recording_id,
            track_id=metadata.track_id,
            sequence=metadata.sequence,
            sample_start=metadata.sample_start,
            sample_count=metadata.sample_count,
            plaintext_sha256=metadata.plaintext_sha256,
            high_water_sample=metadata.sample_start + metadata.sample_count,
            replayed=False,
        )

    async def seal(
        self, *, owner_id: int, command: RecordingSealCommand, idempotency_key: str
    ) -> RecordingSealResponse:
        self.owner_ids.append(owner_id)
        raise AssertionError("not used in this route test")

    async def status(self, *, owner_id: int, recording_id: UUID) -> RecordingStatusResponse:
        self.owner_ids.append(owner_id)
        raise AssertionError("not used in this route test")

    async def pending(self, *, owner_id: int) -> tuple[RecordingStatusResponse, ...]:
        self.owner_ids.append(owner_id)
        return ()


def owner(method: str = "bearer", owner_id: int = 7) -> AuthenticatedOwner:
    return AuthenticatedOwner(
        owner_id=owner_id,
        github_user_id=102269369,
        github_login="fgomensoro",
        session_id=1,
        csrf_hash=None if method == "bearer" else b"c" * 32,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        authentication_method=method,  # type: ignore[arg-type]
    )


def client_for(identity: AuthenticatedOwner) -> tuple[TestClient, StubRecordingService]:
    app = create_app(Settings(
        environment="test", github_user_id=102269369, secure_cookies=False, _env_file=None
    ))
    service = StubRecordingService()
    app.dependency_overrides[get_authenticated_owner] = lambda: identity
    app.dependency_overrides[get_recording_service] = lambda: service
    return TestClient(app), service


def create_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "recording_id": str(RECORDING_ID),
        "started_at": "2026-09-01T16:00:00Z",
        "tracks": [
            {
                "track_id": str(MICROPHONE_ID),
                "kind": "microphone",
                "format": {"channel_count": 1},
                "conversion_version": "tamforge-pcm16-v1",
            },
            {
                "track_id": str(SYSTEM_ID),
                "kind": "system_audio",
                "format": {"channel_count": 2},
                "conversion_version": "tamforge-pcm16-v1",
            },
        ],
    }


def part_headers() -> dict[str, str]:
    body = b"c" * 32
    return {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "part-1",
        "X-TAM-Recording-Schema": "1",
        "X-TAM-Track-Kind": "microphone",
        "X-TAM-Sample-Encoding": "pcm_s16le",
        "X-TAM-Sample-Rate": "48000",
        "X-TAM-Channel-Count": "1",
        "X-TAM-Part-Sequence": "0",
        "X-TAM-Sample-Start": "0",
        "X-TAM-Sample-Count": "8",
        "X-TAM-Plaintext-Length": "16",
        "X-TAM-Ciphertext-Length": str(len(body)),
        "X-TAM-Plaintext-SHA256": hashlib.sha256(b"x" * 16).hexdigest(),
        "X-TAM-Ciphertext-SHA256": hashlib.sha256(body).hexdigest(),
        "X-TAM-Part-Nonce": "AAAAAAAAAAAAAAAA",
        "X-TAM-Part-Key": "A" * 43,
        "X-TAM-Part-Encryption": "aes-256-gcm-hkdf-sha256-v1",
    }


def test_create_and_part_routes_require_native_bearer_and_scope_owner() -> None:
    client, service = client_for(owner())
    with client:
        created = client.post(
            "/api/v1/recordings",
            json=create_payload(),
            headers={"Authorization": "Bearer test-token", "Idempotency-Key": "create-1"},
        )
        part = client.put(
            f"/api/v1/recordings/{RECORDING_ID}/tracks/{MICROPHONE_ID}/parts/0",
            content=b"c" * 32,
            headers=part_headers(),
        )

    assert created.status_code == 201
    assert part.status_code == 201
    assert service.owner_ids == [7, 7]
    assert service.part_key == b"\x00" * 32
    assert "part-key" not in part.text.lower()
    assert part.headers["cache-control"] == "no-store"


def test_recording_routes_reject_cookie_identity_even_with_csrf_shape() -> None:
    client, _ = client_for(owner("cookie"))
    with client:
        response = client.post(
            "/api/v1/recordings",
            json=create_payload(),
            headers={"Idempotency-Key": "create-1", "X-CSRF-Token": "ignored"},
        )

    assert response.status_code == 401


def test_invalid_sensitive_headers_fail_without_echoing_values() -> None:
    client, _ = client_for(owner())
    headers = part_headers()
    headers["X-TAM-Part-Key"] = "SECRET-INVALID-PART-KEY"
    with client:
        response = client.put(
            f"/api/v1/recordings/{RECORDING_ID}/tracks/{MICROPHONE_ID}/parts/0",
            content=b"c" * 32,
            headers=headers,
        )

    assert response.status_code == 422
    assert "SECRET-INVALID-PART-KEY" not in response.text
