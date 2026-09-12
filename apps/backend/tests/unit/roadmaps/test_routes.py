from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.main import create_app
from tamforge_backend.roadmaps.planner import PlannerUnavailable, SchemeProposal
from tamforge_backend.roadmaps.ports import RoadmapImportRecord, RoadmapVersionRecord
from tamforge_backend.roadmaps.routes import get_planner_service, get_roadmap_service
from tamforge_backend.roadmaps.service import InvalidSchemeText

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

    async def snapshot_files(self, object_key: str) -> dict[str, bytes]:
        assert object_key.startswith("roadmap-source/")
        return {"Week 1.md": b"# Week 1\n\n## Day 1\n"}

    async def stage_with_scheme(self, **values: object) -> RoadmapImportRecord:
        assert values["owner_id"] == 1
        assert values["source_key"] == "obsidian-main"
        assert str(values["idempotency_key"]).startswith(("scheme:3:", "reforecast:5:"))
        self.staged_scheme = str(values["yaml_text"])
        record = await self.stage_package(
            owner_id=1,
            package_kind="zip",
            idempotency_key="route-import-1",
            package=type("Package", (), {"accepted": True})(),
        )
        return replace(
            record,
            id=4,
            validation_report={
                "accepted": True,
                "issues": [],
                "scheme_summary": {
                    "program": "Demo",
                    "study_days": 1,
                    "budget_minutes": {"1": 120},
                },
            },
        )

    async def get_version(self, *, owner_id: int, version_id: int) -> RoadmapVersionRecord:
        assert owner_id == 1 and version_id == 5
        return replace(
            self._version(state="active"),
            normalized_payload={
                "scheme": None,
                "tasks": [{"stable_id": "m1-w1-d01-sql"}, {"stable_id": "m1-w1-d01-close"}],
            },
        )

    async def get_source_key(self, *, owner_id: int, source_id: int) -> str:
        assert owner_id == 1 and source_id == 2
        return "obsidian-main"

    async def completed_block_ids(self, *, owner_id: int, version_id: int) -> tuple[str, ...]:
        assert owner_id == 1 and version_id == 5
        return ("m1-w1-d01-sql",)

    async def export_package(self, *, owner_id: int, version_id: int) -> bytes:
        assert owner_id == 1 and version_id == 5
        return b"PK\x05\x06" + b"\x00" * 18

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
        self, *, owner_id: int, version_id: int, timezone: str | None = None
    ) -> RoadmapVersionRecord:
        assert owner_id == 1 and version_id == 5
        self.activated = True
        self.activation_timezone = timezone
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
        activated = client.post(
            "/api/v1/roadmap-versions/5/activate", json={"timezone": "America/Montevideo"}
        )

    assert approved.status_code == 200
    assert approved.json()["state"] == "approved"
    assert activated.status_code == 200
    assert activated.json()["state"] == "active"
    assert service.activated
    assert service.activation_timezone == "America/Montevideo"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"timezone": "Mars/Olympus_Mons"},
        {"timezone": "UTC"},
        {"timezone": "../etc/localtime"},
        {"timezone": "America/Montevideo", "study_start_date": "2026-09-12"},
    ],
)
def test_activation_requires_a_known_iana_timezone(body: dict[str, str] | None) -> None:
    client, service = _client()
    with client:
        activated = client.post("/api/v1/roadmap-versions/5/activate", json=body)

    assert activated.status_code == 422
    assert not service.activated


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
            "scheme_summary": {},
        }
    ]
    assert "normalized_payload" not in response.text


class StubPlanner:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.calls: list[dict[str, object]] = []

    async def generate(self, *, files: dict[str, bytes], instruction: str) -> SchemeProposal:
        self.calls.append({"mode": "generate", "files": files, "instruction": instruction})
        if self.unavailable:
            raise PlannerUnavailable("the planner needs Claude enabled on the server")
        return SchemeProposal(yaml_text="schema_version: 1\n", summary={"study_days": 1}, issues=())

    async def reforecast(self, **values: object) -> SchemeProposal:
        self.calls.append({"mode": "reforecast", **values})
        return SchemeProposal(yaml_text="", summary={}, issues=("day 'x' is over budget",))


def _planner_client(*, unavailable: bool = False) -> tuple[TestClient, StubPlanner]:
    client, _ = _client()
    planner = StubPlanner(unavailable=unavailable)
    client.app.dependency_overrides[get_planner_service] = lambda: planner  # type: ignore[attr-defined]
    return client, planner


def test_generate_proposal_reads_the_snapshot_and_returns_the_scheme() -> None:
    client, planner = _planner_client()
    with client:
        response = client.post(
            "/api/v1/roadmap-imports/3/scheme-proposals", json={"instruction": "three hours"}
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "yaml_text": "schema_version: 1\n",
        "summary": {"study_days": 1},
        "issues": [],
    }
    assert response.headers["cache-control"] == "no-store"
    assert planner.calls[0]["instruction"] == "three hours"
    assert "Week 1.md" in planner.calls[0]["files"]  # type: ignore[operator]


def test_reforecast_proposal_carries_done_blocks_and_refusals_keep_their_issues() -> None:
    client, planner = _planner_client()
    with client:
        response = client.post("/api/v1/roadmap-versions/5/scheme-proposals", json={})

    assert response.status_code == 200, response.text
    assert response.json()["issues"] == ["day 'x' is over budget"]
    evidence = planner.calls[0]["evidence"]
    assert any(line.block_id == "m1-w1-d01-sql" and line.status == "done" for line in evidence)  # type: ignore[union-attr]


def test_planner_unavailable_is_a_503_problem() -> None:
    client, _ = _planner_client(unavailable=True)
    with client:
        response = client.post("/api/v1/roadmap-imports/3/scheme-proposals", json={})

    assert response.status_code == 503
    assert response.json()["code"] == "planner_unavailable"


def test_staging_a_scheme_creates_a_new_import_from_the_snapshot() -> None:
    client, service = _client()
    with client:
        response = client.post(
            "/api/v1/roadmap-imports/3/scheme", json={"yaml_text": "schema_version: 1\n"}
        )
        reforecast = client.post(
            "/api/v1/roadmap-versions/5/reforecasts", json={"yaml_text": "schema_version: 1\n"}
        )

    assert response.status_code == 201, response.text
    assert response.json()["id"] == 4
    assert response.json()["validation_report"]["scheme_summary"]["study_days"] == 1
    assert reforecast.status_code == 201, reforecast.text
    assert service.staged_scheme == "schema_version: 1\n"


def test_unparseable_scheme_text_is_a_422_problem() -> None:
    client, service = _client()

    async def broken(**values: object) -> RoadmapImportRecord:
        raise InvalidSchemeText("roadmap.yaml is not valid YAML")

    service.stage_with_scheme = broken  # type: ignore[method-assign]
    with client:
        response = client.post("/api/v1/roadmap-imports/3/scheme", json={"yaml_text": "days: ["})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_roadmap_scheme"


def test_export_returns_the_package_zip_without_caching() -> None:
    client, _ = _client()
    with client:
        response = client.get("/api/v1/roadmap-versions/5/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith('roadmap-version-5.zip"')
    assert response.content.startswith(b"PK")
