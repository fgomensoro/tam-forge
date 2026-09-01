"""Complete Month 1 foundation journey through real application boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import boto3
import httpx
import pytest
import respx
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"
PARITY_FIXTURE = (
    ROOT / "tests" / "fixtures" / "native-parity" / "foundation-journey-v1.json"
)


def _isolated_object_store() -> dict[str, str]:
    expected = {
        "TAMFORGE_OBJECT_STORE_ENDPOINT": "http://127.0.0.1:9000",
        "TAMFORGE_OBJECT_STORE_BUCKET": "tam-forge-parity-test",
        "TAMFORGE_OBJECT_STORE_ACCESS_KEY": "tamforge",
        "TAMFORGE_OBJECT_STORE_SECRET_KEY": "tamforge-local",
    }
    configured = {name: os.getenv(name) for name in expected}
    if all(value is None for value in configured.values()):
        pytest.skip("isolated MinIO settings are required; tests never autostart Docker")
    mismatched = [
        name for name, expected_value in expected.items() if configured[name] != expected_value
    ]
    if mismatched:
        pytest.fail(
            "isolated MinIO settings must match the locked parity target: "
            + ", ".join(mismatched),
            pytrace=False,
        )
    return expected


@respx.mock
def test_month1_workspace_is_authenticated_resumable_and_idempotent(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.auth.models import CommandReceipt
    from tamforge_backend.auth.service import AuthService
    from tamforge_backend.config import APPROVED_GITHUB_USER_ID, Settings
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.evidence.models import RubricEvaluation, SkillEvidenceEvent
    from tamforge_backend.evidence.repository import SqlAlchemyEvidenceRepository
    from tamforge_backend.evidence.schemas import (
        DimensionEvaluationInput,
        EvidenceEvaluationCommand,
        SkillDimensionSubsetInput,
    )
    from tamforge_backend.evidence.seed import seed_config
    from tamforge_backend.evidence.service import EvidenceService
    from tamforge_backend.learning.models import ActivityInstance, Attempt, SelfReview
    from tamforge_backend.main import create_app
    from tamforge_backend.notifications.models import Notification, OutboxEvent
    from tamforge_backend.notifications.repository import SqlAlchemyNotificationRepository
    from tamforge_backend.roadmaps.models import RoadmapImport
    from tamforge_backend.storage.s3 import S3ObjectStore

    object_store = _isolated_object_store()
    package_bytes = FIXTURE.read_bytes()
    parity = json.loads(PARITY_FIXTURE.read_text(encoding="utf-8"))
    assert parity["source_package"] == {
        "path": "apps/backend/tests/fixtures/roadmaps/month-v1.zip",
        "sha256": hashlib.sha256(package_bytes).hexdigest(),
        "byte_length": len(package_bytes),
    }
    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    s3_client = boto3.client(
        "s3",
        endpoint_url=object_store["TAMFORGE_OBJECT_STORE_ENDPOINT"],
        region_name="us-east-1",
        aws_access_key_id=object_store["TAMFORGE_OBJECT_STORE_ACCESS_KEY"],
        aws_secret_access_key=object_store["TAMFORGE_OBJECT_STORE_SECRET_KEY"],
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    try:
        try:
            s3_client.head_bucket(Bucket=object_store["TAMFORGE_OBJECT_STORE_BUCKET"])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {
                "404",
                "NoSuchBucket",
                "NotFound",
            }:
                raise
            s3_client.create_bucket(Bucket=object_store["TAMFORGE_OBJECT_STORE_BUCKET"])
        command.downgrade(migration, "base")
        command.upgrade(migration, "head")

        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")

        async def exercise() -> None:
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            bundle = load_config_bundle(ROOT / "config")
            settings = Settings(
                environment="test",
                database_url=async_url.render_as_string(hide_password=False),
                github_user_id=APPROVED_GITHUB_USER_ID,
                github_client_id="client-id",
                github_client_secret="provider-secret-not-persisted",
                session_signing_secret="state-signing-secret-with-enough-entropy",
                github_callback_url="https://app.example.test/api/v1/auth/callback",
                cors_origins=["https://app.example.test"],
                secure_cookies=False,
                roadmap_config_dir=ROOT / "config",
                object_store_endpoint=object_store["TAMFORGE_OBJECT_STORE_ENDPOINT"],
                object_store_bucket=object_store["TAMFORGE_OBJECT_STORE_BUCKET"],
                object_store_access_key=object_store[
                    "TAMFORGE_OBJECT_STORE_ACCESS_KEY"
                ],
                object_store_secret_key=object_store[
                    "TAMFORGE_OBJECT_STORE_SECRET_KEY"
                ],
                object_store_region="us-east-1",
                object_store_addressing_style="path",
                github_roadmap_mirror_token="",
                github_roadmap_mirror_repository="",
                _env_file=None,
            )
            app = create_app(settings)
            assert app.dependency_overrides == {}
            transport = ASGITransport(app=app)

            async def mutate(
                client: AsyncClient,
                path: str,
                body: dict[str, object],
                key: str,
            ) -> httpx.Response:
                return await client.post(
                    path,
                    json=body,
                    headers={**native_headers, "Idempotency-Key": key},
                )

            try:
                async with app.router.lifespan_context(app):
                    respx.post("https://github.com/login/oauth/access_token").mock(
                        return_value=httpx.Response(
                            200,
                            json={
                                "access_token": "provider-access-token",
                                "token_type": "bearer",
                            },
                        )
                    )
                    respx.get("https://api.github.com/user").mock(
                        return_value=httpx.Response(
                            200,
                            json={
                                "id": APPROVED_GITHUB_USER_ID,
                                "login": "fgomensoro",
                            },
                        )
                    )
                    verifier = "v" * 43
                    challenge = AuthService.pkce_challenge(verifier)
                    async with AsyncClient(
                        transport=transport,
                        base_url="https://app.example.test",
                    ) as auth_client:
                        started_auth = await auth_client.post(
                            "/api/v1/auth/native/start",
                            json={"code_challenge": challenge},
                        )
                        assert started_auth.status_code == 200
                        state = parse_qs(
                            urlsplit(
                                started_auth.json()["authorization_url"]
                            ).query
                        )["state"][0]
                        callback = await auth_client.get(
                            "/api/v1/auth/callback",
                            params={"code": "provider-code", "state": state},
                            follow_redirects=False,
                        )
                        assert callback.status_code == 303
                        exchange_code = parse_qs(
                            urlsplit(callback.headers["location"]).query
                        )["code"][0]
                        exchanged = await auth_client.post(
                            "/api/v1/auth/native/exchange",
                            json={
                                "code": exchange_code,
                                "code_verifier": verifier,
                            },
                        )
                        assert exchanged.status_code == 200
                        native_headers = {
                            "Authorization": (
                                f"Bearer {exchanged.json()['access_token']}"
                            )
                        }
                        authenticated = await auth_client.get(
                            "/api/v1/auth/native/session",
                            headers=native_headers,
                        )
                        assert authenticated.status_code == 200
                        assert authenticated.json()["github_login"] == "fgomensoro"

                    with sync_engine.begin() as connection:
                        owner_id = connection.execute(
                            text(
                                "SELECT id FROM owners WHERE github_user_id = :github_id"
                            ),
                            {"github_id": APPROVED_GITHUB_USER_ID},
                        ).scalar_one()
                        connection.execute(
                            text(
                                "INSERT INTO learner_settings "
                                "(owner_id, timezone, study_start_date) "
                                "VALUES (:owner, 'America/Los_Angeles', :start_date)"
                            ),
                            {"owner": owner_id, "start_date": date(2026, 8, 24)},
                        )

                    async with AsyncClient(
                        transport=transport,
                        base_url="https://app.example.test",
                    ) as first_native_client:
                        staged = await first_native_client.post(
                            "/api/v1/roadmap-imports",
                            data={"package_kind": "zip"},
                            files={
                                "package": (
                                    "month-v1.zip",
                                    package_bytes,
                                    "application/zip",
                                )
                            },
                            headers={
                                **native_headers,
                                "Idempotency-Key": "foundation-roadmap",
                            },
                        )
                        assert staged.status_code == 201, staged.text
                        staged_payload = staged.json()
                        expected_import = parity["responses"]["roadmap_import"]
                        assert staged_payload["status"] == expected_import["status"]
                        assert staged_payload["failure_code"] == expected_import["failure_code"]
                        assert {
                            key: staged_payload["validation_report"][key]
                            for key in ("accepted", "task_count", "issues")
                        } == {
                            key: expected_import["validation_report"][key]
                            for key in ("accepted", "task_count", "issues")
                        }

                        replay = await first_native_client.post(
                            "/api/v1/roadmap-imports",
                            data={"package_kind": "zip"},
                            files={
                                "package": (
                                    "month-v1.zip",
                                    package_bytes,
                                    "application/zip",
                                )
                            },
                            headers={
                                **native_headers,
                                "Idempotency-Key": "foundation-roadmap",
                            },
                        )
                        assert replay.status_code == 201
                        assert replay.json()["id"] == staged_payload["id"]

                        approved = await first_native_client.post(
                            f"/api/v1/roadmap-imports/{staged_payload['id']}/approve",
                            headers=native_headers,
                        )
                        assert approved.status_code == 200, approved.text
                        approved_payload = approved.json()
                        assert approved_payload["mirror_status"] == "not_required"
                        assert approved_payload["mirror_ref"] is None
                        activated = await first_native_client.post(
                            f"/api/v1/roadmap-versions/{approved_payload['id']}/activate",
                            headers=native_headers,
                        )
                        assert activated.status_code == 200, activated.text
                        activated_payload = activated.json()
                        expected_version = parity["responses"]["roadmap_version"]
                        assert {
                            key: activated_payload[key]
                            for key in (
                                "version_number",
                                "month_number",
                                "state",
                                "mirror_status",
                                "mirror_ref",
                                "mirror_error_code",
                            )
                        } == {
                            key: expected_version[key]
                            for key in (
                                "version_number",
                                "month_number",
                                "state",
                                "mirror_status",
                                "mirror_ref",
                                "mirror_error_code",
                            )
                        }

                        today = await first_native_client.get(
                            "/api/v1/today?date=2026-08-24", headers=native_headers
                        )
                        assert today.status_code == 200, today.text
                        today_payload = today.json()
                        expected_today = parity["responses"]["today"]
                        assert {
                            key: today_payload[key]
                            for key in (
                                "local_date",
                                "timezone",
                                "day_type",
                                "day_status",
                                "total_planned_minutes",
                                "time_policy",
                            )
                        } == {
                            key: expected_today[key]
                            for key in (
                                "local_date",
                                "timezone",
                                "day_type",
                                "day_status",
                                "total_planned_minutes",
                                "time_policy",
                            )
                        }
                        assert {
                            key: today_payload["roadmap"][key]
                            for key in ("version_number", "month", "week", "day")
                        } == {
                            key: expected_today["roadmap"][key]
                            for key in ("version_number", "month", "week", "day")
                        }
                        assert [item["timebox_minutes"] for item in today_payload["tasks"]] == [
                            45,
                            45,
                            30,
                            10,
                            60,
                            35,
                            15,
                        ]
                        reading = next(
                            item
                            for item in today_payload["tasks"]
                            if item["block"] == "technical_learning"
                        )
                        expected_reading = expected_today["tasks"][0]
                        assert reading["block"] == expected_reading["block"]
                        assert reading["timebox_minutes"] == expected_reading[
                            "timebox_minutes"
                        ]
                        activity_id = int(reading["activity_id"])
                        path = f"/api/v1/activities/{activity_id}"
                        detail = await first_native_client.get(path, headers=native_headers)
                        assert detail.status_code == 200
                        detail_payload = detail.json()
                        assert detail_payload["id"] == activity_id
                        assert detail_payload["state"] == reading["state"]
                        assert detail_payload["optimistic_version"] == reading[
                            "optimistic_version"
                        ]
                        task_contract = detail_payload["task_contract"]
                        for key in (
                            "stable_id",
                            "block",
                            "objective",
                            "timebox_minutes",
                            "required",
                            "source_references",
                            "required_output",
                            "pass_criteria",
                            "evidence_requirements",
                            "allowed_ai_role",
                        ):
                            assert task_contract[key] == reading[key]
                        started = await mutate(
                            first_native_client,
                            path + "/start",
                            {"expected_version": 1},
                            "foundation-start",
                        )
                        assert started.status_code == 200
                        paused = await mutate(
                            first_native_client,
                            path + "/pause",
                            {"expected_version": 2, "client_sequence": 1},
                            "foundation-pause",
                        )
                        assert paused.status_code == 200
                        assert paused.json()["state"] == "paused"

                    async with AsyncClient(
                        transport=transport,
                        base_url="https://app.example.test",
                    ) as resumed_native_client:
                        resumed = await mutate(
                            resumed_native_client,
                            path + "/resume",
                            {"expected_version": 3},
                            "foundation-resume",
                        )
                        assert resumed.status_code == 200
                        hidden = await mutate(
                            resumed_native_client,
                            path + "/source-visibility",
                            {"expected_version": 4, "hidden": True},
                            "foundation-hide",
                        )
                        assert hidden.status_code == 200
                        assert hidden.json()["source_hidden"] is True
                        output = parity["journey"]["output"]
                        commit_body = {
                            "expected_version": 5,
                            "client_sequence": 1,
                            "output": output,
                            "artifact_refs": [],
                        }
                        committed = await mutate(
                            resumed_native_client,
                            path + "/commit-output",
                            commit_body,
                            "foundation-commit",
                        )
                        assert committed.status_code == 200, committed.text
                        committed_payload = committed.json()
                        replayed_commit = await mutate(
                            resumed_native_client,
                            path + "/commit-output",
                            commit_body,
                            "foundation-commit",
                        )
                        assert replayed_commit.json() == committed_payload
                        review_body = {
                            "expected_version": 6,
                            **parity["journey"]["self_review"],
                        }
                        reviewed = await mutate(
                            resumed_native_client,
                            path + "/self-review",
                            review_body,
                            "foundation-review",
                        )
                        assert reviewed.status_code == 200, reviewed.text
                        assert reviewed.json()["state"] == "self_review_complete"

                    async with factory() as session:
                        async with transaction_scope(session):
                            await seed_config(
                                bundle,
                                owner_id=owner_id,
                                session=session,
                                apply=True,
                            )
                    exercise_config = bundle.exercise(
                        "integration_diagram_and_explanation"
                    )
                    rubric = bundle.portfolio
                    applicable = tuple(
                        impact
                        for impact in exercise_config.impacts
                        if impact.condition == "always"
                    )
                    evidence_command = EvidenceEvaluationCommand(
                        activity_id=activity_id,
                        attempt_id=int(committed_payload["attempt_id"]),
                        config_version_key=bundle.version_key,
                        exercise_type=exercise_config.slug,
                        mapping_version=exercise_config.mapping_version,
                        formula_version=bundle.formula.version,
                        rubric_slug=rubric.slug,
                        rubric_version=rubric.version,
                        practice_mode=exercise_config.evidence_mode,
                        assistance="ai_after_committed_attempt",
                        evaluator="ai_rubric_reviewer",
                        difficulty="standard",
                        ai_role="reviewer",
                        evaluated_at=datetime.now(UTC),
                        artifact_ids=(),
                        observation_ids=(),
                        transcript_available=False,
                        audio_available=False,
                        written_english_available=False,
                        scored_recording=False,
                        dimensions=tuple(
                            DimensionEvaluationInput(
                                dimension_slug=dimension.slug,
                                availability="scored",
                                score=min(dimension.maximum, Decimal("3")),
                            )
                            for dimension in rubric.dimensions
                        ),
                        skill_dimension_subsets=tuple(
                            SkillDimensionSubsetInput(
                                skill_slug=impact.skill_slug,
                                dimension_slugs=(rubric.dimensions[index].slug,),
                            )
                            for index, impact in enumerate(applicable)
                        ),
                    )
                    async with factory() as session:
                        evidence = await EvidenceService(
                            SqlAlchemyEvidenceRepository(session)
                        ).record(
                            owner_id=owner_id,
                            command=evidence_command,
                            idempotency_key="foundation-evidence",
                        )
                    async with factory() as session:
                        replayed_evidence = await EvidenceService(
                            SqlAlchemyEvidenceRepository(session)
                        ).record(
                            owner_id=owner_id,
                            command=evidence_command,
                            idempotency_key="foundation-evidence",
                        )
                        assert replayed_evidence == evidence
                        reader = SqlAlchemyEvidenceRepository(session)
                        first_projection = await reader.list_skills(owner_id=owner_id)
                    async with factory() as session:
                        second_projection = await SqlAlchemyEvidenceRepository(
                            session
                        ).list_skills(owner_id=owner_id)
                    assert first_projection == second_projection
                    measured = tuple(
                        item
                        for item in first_projection.items
                        if item.latest_snapshot is not None
                    )
                    assert len(measured) == len(applicable)
                    assert all(
                        {
                            item.event_id
                            for item in skill.latest_snapshot.manifest
                        }.issubset(set(evidence.evidence_event_ids))
                        for skill in measured
                    )

                    now = datetime.now(UTC)
                    async with factory() as session:
                        async with transaction_scope(session):
                            session.add(
                                OutboxEvent(
                                    owner_id=owner_id,
                                    aggregate_type="activity",
                                    aggregate_id=activity_id,
                                    event_type="activity.feedback_ready",
                                    payload_schema_version=1,
                                    payload={
                                        "schema_version": 1,
                                        "subject_id": activity_id,
                                    },
                                    occurred_at=now,
                                    published_at=None,
                                    attempts=0,
                                    idempotency_key="foundation-feedback",
                                )
                            )
                    async with factory() as session:
                        delivery = SqlAlchemyNotificationRepository(session)
                        first_delivery = await delivery.deliver_outbox(limit=100)
                        second_delivery = await delivery.deliver_outbox(limit=100)
                        assert len(first_delivery.notification_ids) == 1
                        assert second_delivery.notification_ids == ()

                    async with AsyncClient(
                        transport=transport,
                        base_url="https://app.example.test",
                    ) as final_native_client:
                        skills = await final_native_client.get(
                            "/api/v1/skills", headers=native_headers
                        )
                        assert skills.status_code == 200
                        expected_unassessed = next(
                            item
                            for item in parity["responses"]["skills"]["items"]
                            if item["latest_snapshot"] is None
                        )
                        actual_unassessed = next(
                            item
                            for item in skills.json()["items"]
                            if item["slug"] == expected_unassessed["slug"]
                        )
                        assert actual_unassessed == expected_unassessed
                        portfolio = await final_native_client.get(
                            "/api/v1/portfolio-judgment", headers=native_headers
                        )
                        assert portfolio.status_code == 200
                        assert portfolio.json()["items"] == []
                        assert portfolio.json()["next_cursor"] is None

                        notifications = await final_native_client.get(
                            "/api/v1/notifications", headers=native_headers
                        )
                        assert notifications.status_code == 200
                        notification = notifications.json()["items"][0]
                        expected_notification = parity["responses"]["notifications"][
                            "items"
                        ][0]
                        assert notification["notification_type"] == expected_notification[
                            "notification_type"
                        ]
                        assert notification["subject_kind"] == expected_notification[
                            "subject_kind"
                        ]
                        assert notification["subject_id"] == activity_id
                        assert notification["read_at"] is None
                        notification_id = notification["id"]
                        first_read = await final_native_client.post(
                            f"/api/v1/notifications/{notification_id}/read",
                            headers=native_headers,
                        )
                        second_read = await final_native_client.post(
                            f"/api/v1/notifications/{notification_id}/read",
                            headers=native_headers,
                        )
                        assert first_read.status_code == second_read.status_code == 200
                        assert first_read.json()["read_at"] == second_read.json()["read_at"]
                        refreshed_today = await final_native_client.get(
                            "/api/v1/today?date=2026-08-24", headers=native_headers
                        )
                        updated = next(
                            item
                            for item in refreshed_today.json()["tasks"]
                            if item["activity_id"] == activity_id
                        )
                        assert updated["state"] == "self_review_complete"

                async with factory() as session:
                    assert await session.scalar(
                        select(func.count()).select_from(RoadmapImport)
                    ) == 1
                    assert await session.scalar(
                        select(func.count()).select_from(Attempt)
                    ) == 1
                    assert await session.scalar(
                        select(func.count()).select_from(SelfReview)
                    ) == 1
                    assert await session.scalar(
                        select(func.count()).select_from(RubricEvaluation)
                    ) == 1
                    assert await session.scalar(
                        select(func.count()).select_from(SkillEvidenceEvent)
                    ) == len(applicable)
                    assert await session.scalar(
                        select(func.count()).select_from(Notification)
                    ) == 1
                    assert await session.scalar(
                        select(func.count())
                        .select_from(CommandReceipt)
                        .where(CommandReceipt.command_scope == "activity.commit-output")
                    ) == 1
                    activity = await session.get(ActivityInstance, activity_id)
                    assert activity is not None
                    assert activity.state == "self_review_complete"
                    persisted_import = (
                        await session.scalars(select(RoadmapImport))
                    ).one()
                    object_key = persisted_import.object_key
                    assert persisted_import.package_hash.hex() == parity[
                        "source_package"
                    ]["sha256"]

                fresh_store = S3ObjectStore(
                    endpoint_url=object_store["TAMFORGE_OBJECT_STORE_ENDPOINT"],
                    region="us-east-1",
                    bucket=object_store["TAMFORGE_OBJECT_STORE_BUCKET"],
                    access_key=object_store["TAMFORGE_OBJECT_STORE_ACCESS_KEY"],
                    secret_key=object_store["TAMFORGE_OBJECT_STORE_SECRET_KEY"],
                )
                stored = await fresh_store.stat(object_key)
                assert stored is not None
                assert stored.sha256 == parity["source_package"]["sha256"]
                assert stored.byte_length == parity["source_package"]["byte_length"]
                async with fresh_store.open(object_key) as chunks:
                    persisted_package = b"".join([chunk async for chunk in chunks])
                assert persisted_package == package_bytes
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
