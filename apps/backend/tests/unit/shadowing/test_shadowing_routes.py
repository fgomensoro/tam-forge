from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.learning.schemas import PresignedUploadResponse
from tamforge_backend.main import create_app
from tamforge_backend.shadowing.routes import get_shadowing_service
from tamforge_backend.shadowing.schemas import (
    ExcerptConfirmCommand,
    ExcerptDownloadResponse,
    ExcerptUploadCommand,
    ExcerptUploadResponse,
    ShadowingClipCommand,
    ShadowingClipPage,
    ShadowingClipResponse,
    ShadowingExcerptResponse,
)
from tamforge_backend.shadowing.service import (
    ShadowingConflict,
    ShadowingInvalid,
    ShadowingNotFound,
    ShadowingUnavailable,
)

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)
NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
DIGEST = "a" * 64
BODY: dict[str, Any] = {
    "title": "QBR opening",
    "format": "solo",
    "skill_slug": "english_fluency",
    "source_note": "Recorded talk, minute 3",
    "license_note": "CC BY 4.0",
    "duration_ms": 45_000,
    "phrases": [
        {"index": 0, "start_ms": 0, "end_ms": 2_000, "text": "Thanks for joining.", "enabled": True}
    ],
}


def _clip(
    command: ShadowingClipCommand, clip_id: int = 7, *, uploaded: bool = False
) -> ShadowingClipResponse:
    return ShadowingClipResponse(
        id=clip_id,
        title=command.title,
        format=command.format,
        skill_slug=command.skill_slug,
        source_note=command.source_note,
        license_note=command.license_note,
        duration_ms=command.duration_ms,
        phrases=command.phrases,
        annotations=(),
        preparation_state="pending",
        excerpt=(
            ShadowingExcerptResponse(sha256=DIGEST, byte_length=1_024, content_type="audio/mp4")
            if uploaded
            else None
        ),
        created_at=NOW,
        updated_at=NOW,
    )


class StubService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.command = ShadowingClipCommand.model_validate(BODY)

    def _record(self, name: str, **values: object) -> None:
        self.calls.append((name, values))
        if self.error is not None:
            raise self.error

    async def list(self, *, owner_id: int) -> ShadowingClipPage:
        self._record("list", owner_id=owner_id)
        return ShadowingClipPage(items=(_clip(self.command),))

    async def create(
        self, *, owner_id: int, command: ShadowingClipCommand
    ) -> ShadowingClipResponse:
        self._record("create", owner_id=owner_id, command=command)
        return _clip(command)

    async def get(self, *, owner_id: int, clip_id: int) -> ShadowingClipResponse:
        self._record("get", owner_id=owner_id, clip_id=clip_id)
        return _clip(self.command, clip_id)

    async def replace(
        self, *, owner_id: int, clip_id: int, command: ShadowingClipCommand
    ) -> ShadowingClipResponse:
        self._record("replace", owner_id=owner_id, clip_id=clip_id, command=command)
        return _clip(command, clip_id)

    async def delete(self, *, owner_id: int, clip_id: int) -> None:
        self._record("delete", owner_id=owner_id, clip_id=clip_id)

    async def presign_excerpt(
        self, *, owner_id: int, clip_id: int, command: ExcerptUploadCommand
    ) -> ExcerptUploadResponse:
        self._record("presign", owner_id=owner_id, clip_id=clip_id, command=command)
        return ExcerptUploadResponse(
            upload=PresignedUploadResponse(
                url="https://object-store.invalid/upload?signed=1",
                method="PUT",
                headers={"content-type": command.content_type},
                expires_seconds=300,
            )
        )

    async def confirm_excerpt(
        self, *, owner_id: int, clip_id: int, command: ExcerptConfirmCommand
    ) -> ShadowingClipResponse:
        self._record("confirm", owner_id=owner_id, clip_id=clip_id, command=command)
        return _clip(self.command, clip_id, uploaded=True)

    async def excerpt_download(self, *, owner_id: int, clip_id: int) -> ExcerptDownloadResponse:
        self._record("download", owner_id=owner_id, clip_id=clip_id)
        return ExcerptDownloadResponse(
            url="https://object-store.invalid/download?signed=1",
            expires_seconds=300,
            sha256=DIGEST,
            byte_length=1_024,
            content_type="audio/mp4",
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
    app.dependency_overrides[get_shadowing_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_clip_crud_round_trip_is_owner_scoped_and_never_cached() -> None:
    client, service = _client()
    with client:
        created = client.post("/api/v1/shadowing-clips", json=BODY)
        listed = client.get("/api/v1/shadowing-clips")
        fetched = client.get("/api/v1/shadowing-clips/7")
        replaced = client.put("/api/v1/shadowing-clips/7", json={**BODY, "title": "Take 2"})
        deleted = client.delete("/api/v1/shadowing-clips/7")

    assert created.status_code == 201, created.text
    assert created.json()["excerpt"] is None and created.json()["annotations"] == []
    assert created.json()["preparation_state"] == "pending"
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1
    assert fetched.status_code == 200 and fetched.json()["id"] == 7
    assert replaced.status_code == 200 and replaced.json()["title"] == "Take 2"
    assert deleted.status_code == 204 and deleted.content == b""
    for response in (created, listed, fetched, replaced, deleted):
        assert response.headers["cache-control"] == "no-store"
    assert [name for name, _ in service.calls] == ["create", "list", "get", "replace", "delete"]
    assert all(values["owner_id"] == 1 for _, values in service.calls)
    assert service.calls[3][1]["clip_id"] == 7


def test_excerpt_upload_confirm_and_download() -> None:
    client, service = _client()
    with client:
        signed = client.post(
            "/api/v1/shadowing-clips/7/excerpt/upload",
            json={"sha256": DIGEST, "byte_length": 1_024, "content_type": "audio/mp4"},
        )
        confirmed = client.post(
            "/api/v1/shadowing-clips/7/excerpt/confirm", json={"sha256": DIGEST}
        )
        download = client.get("/api/v1/shadowing-clips/7/excerpt/download")

    assert signed.status_code == 200, signed.text
    assert signed.json()["upload"]["method"] == "PUT"
    assert signed.json()["upload"]["headers"] == {"content-type": "audio/mp4"}
    assert confirmed.status_code == 200 and confirmed.json()["excerpt"]["sha256"] == DIGEST
    assert download.status_code == 200 and download.json()["expires_seconds"] == 300
    assert "object_key" not in signed.text + confirmed.text + download.text
    for response in (signed, confirmed, download):
        assert response.headers["cache-control"] == "no-store"
    assert [name for name, _ in service.calls] == ["presign", "confirm", "download"]


def test_invalid_commands_never_reach_the_service() -> None:
    client, service = _client()
    overlapping = [
        {"index": 0, "start_ms": 0, "end_ms": 2_000, "text": "One.", "enabled": True},
        {"index": 1, "start_ms": 1_000, "end_ms": 3_000, "text": "Two.", "enabled": True},
    ]
    with client:
        responses = [
            client.post("/api/v1/shadowing-clips", json={**BODY, "title": ""}),
            client.post("/api/v1/shadowing-clips", json={**BODY, "format": "trio"}),
            client.post("/api/v1/shadowing-clips", json={**BODY, "phrases": overlapping}),
            client.put("/api/v1/shadowing-clips/7", json={**BODY, "duration_ms": 120_001}),
            client.post("/api/v1/shadowing-clips", json={**BODY, "x": 1}),
            client.post(
                "/api/v1/shadowing-clips/7/excerpt/upload",
                json={"sha256": DIGEST, "byte_length": 1_024, "content_type": "audio/mpeg"},
            ),
            client.post(
                "/api/v1/shadowing-clips/7/excerpt/upload",
                json={"sha256": DIGEST, "byte_length": 104_857_601, "content_type": "video/mp4"},
            ),
            client.post("/api/v1/shadowing-clips/7/excerpt/confirm", json={"sha256": "nope"}),
        ]

    assert {response.status_code for response in responses} == {422}
    assert service.calls == []


def test_service_errors_are_closed_problems() -> None:
    client, service = _client()
    expected = (
        (ShadowingNotFound("internal clip detail"), 404, "shadowing_clip_not_found"),
        (ShadowingInvalid("internal clip detail"), 422, "invalid_shadowing_command"),
        (ShadowingConflict("internal clip detail"), 409, "shadowing_conflict"),
        (ShadowingUnavailable("internal clip detail"), 503, "shadowing_unavailable"),
    )
    with client:
        for error, status, code in expected:
            service.error = error
            response = client.post(
                "/api/v1/shadowing-clips/9/excerpt/confirm", json={"sha256": DIGEST}
            )
            assert response.status_code == status
            assert response.json()["code"] == code
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.headers["cache-control"] == "no-store"
            assert "internal clip detail" not in response.text


def test_the_contract_lists_every_shadowing_operation() -> None:
    client, _ = _client()
    with client:
        paths = client.app.openapi()["paths"]  # type: ignore[attr-defined]

    assert set(paths["/api/v1/shadowing-clips"]) == {"get", "post"}
    assert set(paths["/api/v1/shadowing-clips/{clip_id}"]) == {"get", "put", "delete"}
    assert set(paths["/api/v1/shadowing-clips/{clip_id}/excerpt/upload"]) == {"post"}
    assert set(paths["/api/v1/shadowing-clips/{clip_id}/excerpt/confirm"]) == {"post"}
    assert set(paths["/api/v1/shadowing-clips/{clip_id}/excerpt/download"]) == {"get"}
