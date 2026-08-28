from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"


def test_universal_workspace_commits_immutable_output_then_requires_self_review(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.auth.dependencies import (
        get_authenticated_owner,
        require_csrf_owner,
    )
    from tamforge_backend.auth.models import CommandReceipt
    from tamforge_backend.auth.schemas import AuthenticatedOwner
    from tamforge_backend.config import Settings
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.learning.models import (
        ActivityArtifactLink,
        ActivityInstance,
        Artifact,
        Attempt,
        LearnerSetting,
        SelfReview,
    )
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.learning.routes import (
        get_activity_service,
        get_activity_storage_service,
    )
    from tamforge_backend.learning.service import ActivityService
    from tamforge_backend.main import create_app
    from tamforge_backend.roadmaps.models import TaskDefinition
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()

        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")

        async def exercise() -> None:
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            object_store = InMemoryObjectStore()
            clock = {"now": datetime(2026, 8, 24, 19, tzinfo=UTC)}
            try:
                async with factory() as session:
                    roadmap_service = RoadmapService(
                        config=load_config_bundle(ROOT / "config"),
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=object_store,
                        mirror=None,
                    )
                    with inspect_zip_stream((FIXTURE.read_bytes(),)) as package:
                        staged = await roadmap_service.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="workspace-roadmap",
                            package=package,
                        )
                    approved = await roadmap_service.approve_import(
                        owner_id=owner_id,
                        import_id=staged.id,
                    )
                    async with transaction_scope(session):
                        session.add(
                            LearnerSetting(
                                owner_id=owner_id,
                                timezone="America/Los_Angeles",
                                study_start_date=date(2026, 8, 24),
                                active_roadmap_version_id=None,
                            )
                        )
                    await roadmap_service.activate_version(
                        owner_id=owner_id,
                        version_id=approved.id,
                    )
                    day = await StudyDayService(session).ensure_current_day(
                        owner_id=owner_id,
                        at=clock["now"],
                    )
                    assert day is not None
                    activity_id = (
                        await session.execute(
                            select(ActivityInstance.id)
                            .join(
                                TaskDefinition,
                                (TaskDefinition.owner_id == ActivityInstance.owner_id)
                                & (TaskDefinition.id == ActivityInstance.task_definition_id),
                            )
                            .where(ActivityInstance.owner_id == owner_id)
                            .where(ActivityInstance.study_day_id == day.id)
                            .where(TaskDefinition.block == "communication_spoken")
                        )
                    ).scalar_one()
                    unbound_activity_id = (
                        await session.execute(
                            select(ActivityInstance.id)
                            .join(
                                TaskDefinition,
                                (TaskDefinition.owner_id == ActivityInstance.owner_id)
                                & (TaskDefinition.id == ActivityInstance.task_definition_id),
                            )
                            .where(ActivityInstance.owner_id == owner_id)
                            .where(ActivityInstance.study_day_id == day.id)
                            .where(TaskDefinition.block == "daily_close")
                        )
                    ).scalar_one()
                    activity = await session.get(ActivityInstance, activity_id)
                    assert activity is not None
                    clock["now"] = activity.created_at + timedelta(seconds=1)

                owner = AuthenticatedOwner(
                    owner_id=owner_id,
                    github_user_id=102269369,
                    github_login="fgomensoro",
                    session_id=1,
                    csrf_hash=b"c" * 32,
                    expires_at=clock["now"] + timedelta(hours=1),
                )
                settings = Settings(
                    environment="test",
                    database_url=async_url.render_as_string(hide_password=False),
                    github_user_id=102269369,
                    secure_cookies=False,
                    _env_file=None,
                )
                app = create_app(settings)

                async def service_dependency() -> AsyncIterator[ActivityService]:
                    async with factory() as request_session:
                        yield ActivityService(
                            request_session,
                            clock=lambda: clock["now"],
                            object_store=object_store,
                        )

                app.dependency_overrides[get_activity_service] = service_dependency
                app.dependency_overrides[get_activity_storage_service] = service_dependency
                app.dependency_overrides[get_authenticated_owner] = lambda: owner
                app.dependency_overrides[require_csrf_owner] = lambda: owner
                transport = ASGITransport(app=app)

                async def request(
                    method: str,
                    path: str,
                    *,
                    json: dict[str, object] | None = None,
                    idempotency_key: str | None = None,
                ) -> tuple[int, dict[str, object]]:
                    headers = (
                        {"Idempotency-Key": idempotency_key}
                        if idempotency_key is not None
                        else None
                    )
                    async with AsyncClient(
                        transport=transport,
                        base_url="https://tamforge.test",
                    ) as client:
                        response = await client.request(
                            method,
                            path,
                            json=json,
                            headers=headers,
                        )
                    return response.status_code, response.json()

                path = f"/api/v1/activities/{activity_id}"
                status, started = await request(
                    "POST",
                    path + "/start",
                    json={"expected_version": 1},
                    idempotency_key="workspace-start",
                )
                assert status == 200, started
                assert started["state"] == "active"

                clock["now"] += timedelta(seconds=12)
                status, heartbeat = await request(
                    "POST",
                    path + "/heartbeat",
                    json={"expected_version": 2, "client_sequence": 1},
                    idempotency_key="workspace-heartbeat",
                )
                assert status == 200
                assert heartbeat["activity_focused_seconds"] == 12

                body = b"answer"
                digest = hashlib.sha256(body).hexdigest()
                presign_command = {
                    "expected_version": 2,
                    "artifact_class": "written_output",
                    "sha256": digest,
                    "byte_length": len(body),
                    "content_type": "text/markdown",
                    "original_filename": "answer.md",
                }
                status, presigned = await request(
                    "POST",
                    path + "/artifacts/presign",
                    json=presign_command,
                    idempotency_key="workspace-presign",
                )
                assert status == 200
                assert presigned["reused"] is False
                assert presigned["upload"]["method"] == "PUT"  # type: ignore[index]
                object_key = str(presigned["object_key"])

                async def chunks() -> AsyncIterator[bytes]:
                    yield body

                await object_store.put_immutable(
                    key=object_key,
                    body=chunks(),
                    sha256=digest,
                    content_type="text/markdown",
                    metadata={"activity-id": str(activity_id), "owner-id": str(owner_id)},
                )
                confirm_command = {
                    "expected_version": 2,
                    "upload_idempotency_key": "workspace-presign",
                    "object_key": object_key,
                }
                status, confirmed = await request(
                    "POST",
                    path + "/artifacts/confirm",
                    json=confirm_command,
                    idempotency_key="workspace-confirm",
                )
                assert status == 200
                artifact_id = int(confirmed["id"])
                status, duplicate_confirm = await request(
                    "POST",
                    path + "/artifacts/confirm",
                    json=confirm_command,
                    idempotency_key="workspace-confirm",
                )
                assert status == 200
                assert duplicate_confirm == confirmed

                unbound_path = f"/api/v1/activities/{unbound_activity_id}"
                status, _ = await request(
                    "POST",
                    unbound_path + "/start",
                    json={"expected_version": 1},
                    idempotency_key="workspace-unbound-start",
                )
                assert status == 200
                unbound_output = {
                    "contract_version": 1,
                    "kind": "writing",
                    "prompt": "Close the study day.",
                    "audience": "Future self",
                    "time_limit_minutes": 15,
                    "requested_action": "Record the most important next correction.",
                    "facts": ["The recommendation arrived late."],
                    "unknowns": ["Whether the issue transfers to a new scenario."],
                    "tone": "Direct",
                    "word_or_character_limit": "100 words",
                    "draft_markdown": "Lead with the recommendation in the next attempt.",
                    "self_edit_notes": "Kept one measurable correction.",
                }
                status, unbound = await request(
                    "POST",
                    unbound_path + "/commit-output",
                    json={
                        "expected_version": 2,
                        "client_sequence": 1,
                        "output": unbound_output,
                        "artifact_refs": [
                            {"artifact_id": artifact_id, "link_role": "original_output"}
                        ],
                    },
                    idempotency_key="workspace-unbound-commit",
                )
                assert status == 422
                assert unbound["code"] == "invalid_activity_command"

                status, current = await request("GET", path)
                assert status == 200, current
                assert current["state"] == "active", current
                assert current["optimistic_version"] == 2, current
                status, hidden = await request(
                    "POST",
                    path + "/source-visibility",
                    json={"expected_version": 2, "hidden": True},
                    idempotency_key="workspace-hide-source",
                )
                assert status == 200, hidden
                assert hidden["source_hidden"] is True
                assert hidden["optimistic_version"] == 3

                output = {
                    "contract_version": 1,
                    "kind": "writing",
                    "prompt": "Explain your approach to a technical hiring manager.",
                    "audience": "Technical hiring manager",
                    "time_limit_minutes": 35,
                    "requested_action": "Evaluate the proposed troubleshooting approach.",
                    "facts": ["The API is returning intermittent 504 responses."],
                    "unknowns": ["Which dependency consumes the timeout budget."],
                    "tone": "Structured and concise",
                    "word_or_character_limit": "Two minutes",
                    "draft_markdown": "I would first establish scope, timing, and impact.",
                    "self_edit_notes": "Moved the customer impact before implementation detail.",
                }
                commit_command = {
                    "expected_version": 3,
                    "client_sequence": 2,
                    "output": output,
                    "artifact_refs": [{"artifact_id": artifact_id, "link_role": "original_output"}],
                }
                clock["now"] += timedelta(seconds=8)
                status, committed = await request(
                    "POST",
                    path + "/commit-output",
                    json=commit_command,
                    idempotency_key="workspace-commit",
                )
                assert status == 200
                assert committed["state"] == "output_committed"
                assert committed["optimistic_version"] == 4
                assert len(str(committed["commitment_sha256"])) == 64
                status, duplicate_commit = await request(
                    "POST",
                    path + "/commit-output",
                    json=commit_command,
                    idempotency_key="workspace-commit",
                )
                assert status == 200
                assert duplicate_commit == committed

                status, stale_upload = await request(
                    "POST",
                    path + "/artifacts/presign",
                    json=presign_command,
                    idempotency_key="workspace-presign",
                )
                assert status == 409
                assert stale_upload["code"] == "activity_state_conflict"

                status, edit_rejected = await request(
                    "POST",
                    path + "/commit-output",
                    json={**commit_command, "output": {**output, "tone": "Changed"}},
                    idempotency_key="workspace-edit-attempt",
                )
                assert status == 409
                assert edit_rejected["code"] == "activity_state_conflict"

                review_command = {
                    "expected_version": 4,
                    "main_answer": "Establish scope, impact, evidence, and next action.",
                    "did_well": "I separated facts from assumptions.",
                    "structure_weakness": "The recommendation arrived too late.",
                    "vague_points": "I did not name a customer update checkpoint.",
                    "hesitation_points": "I paused before explaining the timeout budget.",
                    "change_next": "Lead with the recommendation and checkpoint.",
                    "self_score": 3,
                }
                status, reviewed = await request(
                    "POST",
                    path + "/self-review",
                    json=review_command,
                    idempotency_key="workspace-self-review",
                )
                assert status == 200
                assert reviewed["state"] == "self_review_complete"
                assert reviewed["optimistic_version"] == 5
                status, duplicate_review = await request(
                    "POST",
                    path + "/self-review",
                    json=review_command,
                    idempotency_key="workspace-self-review",
                )
                assert status == 200
                assert duplicate_review == reviewed

                status, reloaded = await request("GET", path)
                assert status == 200
                assert reloaded["state"] == "self_review_complete"
                assert reloaded["task_contract"]["objective"] == (
                    "Read H1 and H5; record a 90-second Tell Me About Yourself, "
                    "with the second attempt unscripted."
                )
                assert reloaded["task_contract"]["allowed_ai_role"] == "interviewer"
                assert reloaded["open_timer"] is None
                assert reloaded["activity_focused_seconds"] == 20
                expected_output = {
                    key: value for key, value in output.items() if key != "contract_version"
                }
                assert reloaded["committed_output"]["contract_payload"]["output"] == expected_output  # type: ignore[index]
                assert reloaded["self_review"]["self_score"] == 3  # type: ignore[index]

                async with factory() as verification_session:
                    attempt = (
                        await verification_session.execute(
                            select(Attempt).where(Attempt.activity_instance_id == activity_id)
                        )
                    ).scalar_one()
                    artifact = await verification_session.get(Artifact, artifact_id)
                    link = (
                        await verification_session.execute(
                            select(ActivityArtifactLink).where(
                                ActivityArtifactLink.activity_instance_id == activity_id,
                                ActivityArtifactLink.attempt_id.is_not(None),
                            )
                        )
                    ).scalar_one()
                    review = (
                        await verification_session.execute(
                            select(SelfReview).where(SelfReview.activity_instance_id == activity_id)
                        )
                    ).scalar_one()
                    presign_receipt = (
                        await verification_session.execute(
                            select(CommandReceipt).where(
                                CommandReceipt.command_scope == "activity.artifact.presign"
                            )
                        )
                    ).scalar_one()
                    assert attempt.original_text is not None
                    assert attempt.commitment_hash.hex() == committed["commitment_sha256"]
                    assert artifact is not None and artifact.content_hash.hex() == digest
                    assert artifact.encryption_metadata["encrypted"] is False
                    assert link.attempt_id == attempt.id
                    assert review.attempt_id == attempt.id
                    assert "url" not in presign_receipt.result_payload
                    assert "upload" not in presign_receipt.result_payload
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        try:
            with sync_engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
        finally:
            sync_engine.dispose()
