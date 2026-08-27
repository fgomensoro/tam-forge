from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.roadmaps.ports import RoadmapImportRecord, RoadmapVersionRecord
from tamforge_backend.roadmaps.routes import get_roadmap_service

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"
OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubRoadmapService:
    def __init__(self) -> None:
        self.approved = False
        self.activated = False

    async def stage_package(self, **values: object) -> RoadmapImportRecord:
        assert values["owner_id"] == 1
        assert values["package_kind"] == "zip"
        assert values["idempotency_key"] == "route-import-1"
        package = values["package"]
        assert package.accepted  # type: ignore[attr-defined]
        return RoadmapImportRecord(
            id=3,
            owner_id=1,
            source_id=2,
            source_key="obsidian-main",
            package_hash="a" * 64,
            object_key="roadmap-source/1/import/" + "a" * 64,
            status="validated",
            validation_report={"accepted": True, "issues": []},
            semantic_diff={"summary": {"added": 321}},
            idempotency_key="route-import-1",
            failure_code=None,
        )

    async def get_import(self, *, owner_id: int, import_id: int) -> RoadmapImportRecord:
        assert owner_id == 1 and import_id == 3
        return await self.stage_package(
            owner_id=1,
            package_kind="zip",
            idempotency_key="route-import-1",
            package=type("Package", (), {"accepted": True})(),
        )

    async def approve_import(self, *, owner_id: int, import_id: int) -> RoadmapVersionRecord:
        assert owner_id == 1 and import_id == 3
        self.approved = True
        return self._version()

    async def retry_mirror(self, *, owner_id: int, version_id: int) -> RoadmapVersionRecord:
        assert owner_id == 1 and version_id == 5
        return self._version(mirror_status="synced", mirror_ref="commit-1")

    async def list_versions(self, *, owner_id: int) -> tuple[RoadmapVersionRecord, ...]:
        assert owner_id == 1
        return (self._version(),)

    async def activate_version(
        self, *, owner_id: int, version_id: int
    ) -> RoadmapVersionRecord:
        assert owner_id == 1 and version_id == 5
        self.activated = True
        return self._version(state="active")

    @staticmethod
    def _version(
        *,
        state: str = "approved",
        mirror_status: str = "not_required",
        mirror_ref: str | None = None,
    ) -> RoadmapVersionRecord:
        return RoadmapVersionRecord(
            id=5,
            owner_id=1,
            source_id=2,
            version_key="month-1-v2",
            version_number=1,
            month_number=1,
            object_key="roadmap-source/1/import/" + "a" * 64,
            content_hash="b" * 64,
            manifest={},
            normalized_payload={},
            state=state,
            mirror_status=mirror_status,
            mirror_ref=mirror_ref,
            mirror_error_code=None,
        )


def _client() -> tuple[TestClient, StubRoadmapService]:
    settings = Settings(
        environment="test",
        github_user_id=102269369,
        cors_origins=["https://app.example.test"],
        secure_cookies=False,
        _env_file=None,
    )
    app = create_app(settings)
    service = StubRoadmapService()
    app.dependency_overrides[get_roadmap_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    return TestClient(app), service


def test_zip_import_returns_validation_and_diff_without_private_storage_fields() -> None:
    client, _ = _client()
    with client:
        response = client.post(
            "/api/v1/roadmap-imports",
            data={"package_kind": "zip"},
            files={"package": ("month-1.zip", FIXTURE.read_bytes(), "application/zip")},
            headers={"Idempotency-Key": "route-import-1"},
        )

    assert response.status_code == 201
    assert response.json() == {
        "id": 3,
        "status": "validated",
        "validation_report": {"accepted": True, "issues": []},
        "semantic_diff": {"summary": {"added": 321}},
        "failure_code": None,
    }
    assert "object_key" not in response.text
    assert "package_hash" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_approval_and_activation_are_separate_explicit_mutations() -> None:
    client, service = _client()
    with client:
        approved = client.post("/api/v1/roadmap-imports/3/approve")
        assert service.approved
        assert not service.activated
        activated = client.post("/api/v1/roadmap-versions/5/activate")

    assert approved.status_code == 200
    assert approved.json()["state"] == "approved"
    assert activated.status_code == 200
    assert activated.json()["state"] == "active"
    assert service.activated


def test_version_listing_exposes_mirror_state_but_not_normalized_payload() -> None:
    client, _ = _client()
    with client:
        response = client.get("/api/v1/roadmap-versions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 5,
            "version_key": "month-1-v2",
            "version_number": 1,
            "month_number": 1,
            "state": "approved",
            "mirror_status": "not_required",
            "mirror_ref": None,
            "mirror_error_code": None,
        }
    ]
    assert "normalized_payload" not in response.text
