from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
from tamforge_backend.auth.schemas import AuthenticatedOwner
from tamforge_backend.config import Settings
from tamforge_backend.learning.enums import ActivityState
from tamforge_backend.learning.routes import (
    get_activity_service,
    get_activity_storage_service,
)
from tamforge_backend.learning.schemas import (
    ActivityDetailResponse,
    ArtifactPresignResponse,
    ArtifactResponse,
    OutputCommitResponse,
    PresignedUploadResponse,
    SelfReviewResponse,
)
from tamforge_backend.main import create_app

OWNER = AuthenticatedOwner(
    owner_id=1,
    github_user_id=102269369,
    github_login="fgomensoro",
    session_id=1,
    csrf_hash=b"c" * 32,
    expires_at=datetime.now(UTC) + timedelta(hours=1),
)


class StubOutputService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def get_activity(self, **values: object) -> ActivityDetailResponse:
        self.calls.append(("get", values))
        return ActivityDetailResponse(
            id=7,
            study_day_id=3,
            state=ActivityState.SELF_REVIEW_COMPLETE,
            optimistic_version=4,
            classification="required",
            stronger_evidence_id=None,
            activity_focused_seconds=12,
            day_focused_minutes=1,
            hard_stop_recommended=False,
            open_timer=None,
            source_hidden=True,
        )

    async def presign_artifact(self, **values: object) -> ArtifactPresignResponse:
        self.calls.append(("presign", values))
        return ArtifactPresignResponse(
            object_key=f"written_output/1/activity-7/{'a' * 64}",
            reused=False,
            upload=PresignedUploadResponse(
                url="https://object-store.invalid/signed",
                method="PUT",
                headers={"content-type": "text/markdown"},
                expires_seconds=300,
            ),
        )

    async def confirm_artifact(self, **values: object) -> ArtifactResponse:
        self.calls.append(("confirm", values))
        return ArtifactResponse(
            id=11,
            sha256="a" * 64,
            byte_length=6,
            content_type="text/markdown",
            original_filename="answer.md",
            artifact_class="written_output",
        )

    async def commit_output(self, **values: object) -> OutputCommitResponse:
        self.calls.append(("commit", values))
        return OutputCommitResponse(
            activity_id=7,
            state=ActivityState.OUTPUT_COMMITTED,
            optimistic_version=3,
            attempt_id=13,
            commitment_sha256="b" * 64,
            artifact_ids=(11,),
        )

    async def submit_self_review(self, **values: object) -> SelfReviewResponse:
        self.calls.append(("self-review", values))
        return SelfReviewResponse(
            activity_id=7,
            state=ActivityState.SELF_REVIEW_COMPLETE,
            optimistic_version=4,
            self_review_id=17,
            attempt_id=13,
            self_score=3,
        )

    async def set_source_visibility(self, **values: object) -> ActivityDetailResponse:
        self.calls.append(("source-visibility", values))
        return await self.get_activity(owner_id=1, activity_id=7)


def test_output_routes_forward_strict_commands_and_prevent_browser_storage() -> None:
    settings = Settings(
        environment="test",
        github_user_id=102269369,
        secure_cookies=False,
        _env_file=None,
    )
    app = create_app(settings)
    service = StubOutputService()
    app.dependency_overrides[get_activity_service] = lambda: service
    app.dependency_overrides[get_activity_storage_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    path = "/api/v1/activities/7"
    headers = {"Idempotency-Key": "output-route-test"}
    output = {
        "contract_version": 1,
        "kind": "writing",
        "prompt": "Write an update.",
        "audience": "Customer",
        "time_limit_minutes": 35,
        "requested_action": "Confirm rollback.",
        "facts": ["Errors rose after release 42."],
        "unknowns": ["Regional scope."],
        "tone": "Calm",
        "word_or_character_limit": "150 words",
        "draft_markdown": "We recommend a rollback.",
        "self_edit_notes": "Removed speculation.",
    }
    with TestClient(app) as client:
        responses = [
            client.post(
                path + "/artifacts/presign",
                headers=headers,
                json={
                    "expected_version": 2,
                    "artifact_class": "written_output",
                    "sha256": "a" * 64,
                    "byte_length": 6,
                    "content_type": "text/markdown",
                    "original_filename": "answer.md",
                },
            ),
            client.post(
                path + "/artifacts/confirm",
                headers=headers,
                json={
                    "expected_version": 2,
                    "upload_idempotency_key": "output-route-test",
                    "object_key": f"written_output/1/activity-7/{'a' * 64}",
                },
            ),
            client.post(
                path + "/source-visibility",
                headers=headers,
                json={"expected_version": 2, "hidden": True},
            ),
            client.post(
                path + "/commit-output",
                headers=headers,
                json={
                    "expected_version": 2,
                    "client_sequence": 2,
                    "output": output,
                    "artifact_refs": [{"artifact_id": 11, "link_role": "original_output"}],
                },
            ),
            client.post(
                path + "/self-review",
                headers=headers,
                json={
                    "expected_version": 3,
                    "main_answer": "Recommend rollback.",
                    "did_well": "Led with the decision.",
                    "structure_weakness": "Risk came late.",
                    "vague_points": "The checkpoint was vague.",
                    "hesitation_points": "Paused before mitigation.",
                    "change_next": "State the checkpoint.",
                    "self_score": 3,
                },
            ),
        ]

    assert [response.status_code for response in responses] == [200] * 5
    assert all(response.headers["cache-control"] == "no-store" for response in responses)
    commands = [(name, values) for name, values in service.calls if name != "get"]
    assert [name for name, _ in commands] == [
        "presign",
        "confirm",
        "source-visibility",
        "commit",
        "self-review",
    ]
    assert commands[0][1]["owner_id"] == 1
    assert commands[0][1]["activity_id"] == 7
    assert commands[3][1]["output"] == output
    assert commands[4][1]["self_score"] == 3


def test_output_routes_require_csrf_and_reject_extra_contract_fields() -> None:
    settings = Settings(
        environment="test",
        github_user_id=102269369,
        secure_cookies=False,
        _env_file=None,
    )
    app = create_app(settings)
    service = StubOutputService()
    app.dependency_overrides[get_activity_service] = lambda: service
    app.dependency_overrides[get_activity_storage_service] = lambda: service
    app.dependency_overrides[get_authenticated_owner] = lambda: OWNER
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/activities/7/source-visibility",
            headers={"Idempotency-Key": "bad-extra"},
            json={"expected_version": 2, "hidden": True, "object_key": "browser/key"},
        )

    assert response.status_code == 422
    assert service.calls == []


def test_upload_route_fails_closed_when_private_storage_is_not_configured() -> None:
    settings = Settings(
        environment="test",
        github_user_id=102269369,
        secure_cookies=False,
        object_store_access_key="",
        object_store_secret_key="",
        _env_file=None,
    )
    app = create_app(settings)
    app.dependency_overrides[require_csrf_owner] = lambda: OWNER
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/activities/7/artifacts/presign",
            headers={"Idempotency-Key": "storage-unavailable"},
            json={
                "expected_version": 2,
                "artifact_class": "written_output",
                "sha256": "a" * 64,
                "byte_length": 6,
                "content_type": "text/markdown",
                "original_filename": "answer.md",
            },
        )

    assert response.status_code == 503
    assert response.json()["code"] == "activity_dependency_unavailable"
    assert "credential" not in response.text.lower()
