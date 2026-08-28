"""Complete Month 1 foundation journey through real application boundaries."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"


def test_month1_workspace_is_authenticated_resumable_and_idempotent(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.auth.crypto import hash_secret
    from tamforge_backend.auth.models import CommandReceipt
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
    from tamforge_backend.roadmaps.ports import MirrorRequest
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.routes import get_roadmap_service
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore

    migration = Config("apps/backend/alembic.ini")
    migration.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    session_token = "s" * 43
    csrf_token = "c" * 43
    try:
        command.downgrade(migration, "base")
        command.upgrade(migration, "head")
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (:github_id, 'fgomensoro') RETURNING id"
                ),
                {"github_id": APPROVED_GITHUB_USER_ID},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO auth_sessions "
                    "(owner_id, token_hash, csrf_hash, created_at, expires_at) "
                    "VALUES (:owner, :token, :csrf, now(), now() + interval '2 hours')"
                ),
                {
                    "owner": owner_id,
                    "token": hash_secret(session_token),
                    "csrf": hash_secret(csrf_token),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO learner_settings "
                    "(owner_id, timezone, study_start_date) "
                    "VALUES (:owner, 'America/Los_Angeles', :start_date)"
                ),
                {"owner": owner_id, "start_date": date(2026, 8, 24)},
            )

        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")

        async def exercise() -> None:
            events: list[str] = []

            class RecordingStore(InMemoryObjectStore):
                async def put_immutable(self, **kwargs):  # type: ignore[no-untyped-def]
                    result = await super().put_immutable(**kwargs)
                    events.append("object.put")
                    return result

            class RecordingRepository(SqlAlchemyRoadmapRepository):
                async def create_staged_import(self, **kwargs):  # type: ignore[no-untyped-def]
                    events.append("database.reference")
                    return await super().create_staged_import(**kwargs)

            class PrivateMirror:
                enabled = True

                def __init__(self) -> None:
                    self.requests: list[MirrorRequest] = []

                async def mirror(self, request: MirrorRequest) -> str:
                    self.requests.append(request)
                    return "a" * 40

            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            store = RecordingStore()
            mirror = PrivateMirror()
            bundle = load_config_bundle(ROOT / "config")
            settings = Settings(
                environment="test",
                database_url=async_url.render_as_string(hide_password=False),
                github_user_id=APPROVED_GITHUB_USER_ID,
                github_client_id="test-client",
                github_client_secret="test-client-secret",
                session_signing_secret="test-session-signing-secret-0123456789abcdef",
                cors_origins=["http://app.test"],
                secure_cookies=False,
                roadmap_config_dir=ROOT / "config",
                _env_file=None,
            )
            app = create_app(settings)
            app.state.object_store = store

            async def roadmap_dependency():  # type: ignore[no-untyped-def]
                async with factory() as session:
                    yield RoadmapService(
                        config=bundle,
                        repository=RecordingRepository(session),
                        object_store=store,
                        mirror=mirror,
                    )

            app.dependency_overrides[get_roadmap_service] = roadmap_dependency
            transport = ASGITransport(app=app)
            cookies = {
                "tamforge_session": session_token,
                "tamforge_csrf": csrf_token,
            }
            browser_headers = {
                "Origin": "http://app.test",
                "X-CSRF-Token": csrf_token,
            }

            async def mutate(
                client: AsyncClient,
                path: str,
                body: dict[str, object],
                key: str,
            ):  # type: ignore[no-untyped-def]
                return await client.post(
                    path,
                    json=body,
                    headers={**browser_headers, "Idempotency-Key": key},
                )

            try:
                async with app.router.lifespan_context(app):
                    async with AsyncClient(
                        transport=transport,
                        base_url="http://app.test",
                        cookies=cookies,
                    ) as first_browser:
                        authenticated = await first_browser.get("/api/v1/auth/session")
                        assert authenticated.status_code == 200
                        assert authenticated.json()["github_login"] == "fgomensoro"

                        staged = await first_browser.post(
                            "/api/v1/roadmap-imports",
                            data={"package_kind": "zip"},
                            files={
                                "package": (
                                    "month-v1.zip",
                                    FIXTURE.read_bytes(),
                                    "application/zip",
                                )
                            },
                            headers={
                                **browser_headers,
                                "Idempotency-Key": "foundation-roadmap",
                            },
                        )
                        assert staged.status_code == 201, staged.text
                        staged_payload = staged.json()
                        assert staged_payload["status"] == "validated"
                        assert staged_payload["validation_report"]["accepted"] is True
                        assert events == ["object.put", "database.reference"]

                        replay = await first_browser.post(
                            "/api/v1/roadmap-imports",
                            data={"package_kind": "zip"},
                            files={
                                "package": (
                                    "month-v1.zip",
                                    FIXTURE.read_bytes(),
                                    "application/zip",
                                )
                            },
                            headers={
                                **browser_headers,
                                "Idempotency-Key": "foundation-roadmap",
                            },
                        )
                        assert replay.status_code == 201
                        assert replay.json()["id"] == staged_payload["id"]
                        assert events == ["object.put", "database.reference"]

                        approved = await first_browser.post(
                            f"/api/v1/roadmap-imports/{staged_payload['id']}/approve",
                            headers=browser_headers,
                        )
                        assert approved.status_code == 200, approved.text
                        approved_payload = approved.json()
                        assert approved_payload["mirror_status"] == "synced"
                        assert approved_payload["mirror_ref"] == "a" * 40
                        assert len(mirror.requests) == 1
                        activated = await first_browser.post(
                            f"/api/v1/roadmap-versions/{approved_payload['id']}/activate",
                            headers=browser_headers,
                        )
                        assert activated.status_code == 200, activated.text
                        assert activated.json()["state"] == "active"

                        today = await first_browser.get(
                            "/api/v1/today?date=2026-08-24"
                        )
                        assert today.status_code == 200, today.text
                        today_payload = today.json()
                        assert today_payload["total_planned_minutes"] == 240
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
                        activity_id = int(reading["activity_id"])
                        path = f"/api/v1/activities/{activity_id}"
                        started = await mutate(
                            first_browser,
                            path + "/start",
                            {"expected_version": 1},
                            "foundation-start",
                        )
                        assert started.status_code == 200
                        paused = await mutate(
                            first_browser,
                            path + "/pause",
                            {"expected_version": 2, "client_sequence": 1},
                            "foundation-pause",
                        )
                        assert paused.status_code == 200
                        assert paused.json()["state"] == "paused"

                    async with AsyncClient(
                        transport=transport,
                        base_url="http://app.test",
                        cookies=cookies,
                    ) as resumed_browser:
                        resumed = await mutate(
                            resumed_browser,
                            path + "/resume",
                            {"expected_version": 3},
                            "foundation-resume",
                        )
                        assert resumed.status_code == 200
                        hidden = await mutate(
                            resumed_browser,
                            path + "/source-visibility",
                            {"expected_version": 4, "hidden": True},
                            "foundation-hide",
                        )
                        assert hidden.status_code == 200
                        assert hidden.json()["source_hidden"] is True
                        output = {
                            "contract_version": 1,
                            "kind": "reading",
                            "prompt": reading["objective"],
                            "audience": "Technical hiring manager",
                            "time_limit_minutes": 45,
                            "key_ideas": [
                                "HTTP methods make the requested operation explicit.",
                                "Status classes distinguish client and server failures.",
                                "Customer impact must remain separate from protocol status.",
                            ],
                            "boundary_or_failure": (
                                "A successful response does not prove a business outcome."
                            ),
                            "tam_customer_example": (
                                "Confirm order state before advising a customer to retry."
                            ),
                            "unresolved_question": (
                                "Which business errors are returned with HTTP 200?"
                            ),
                        }
                        commit_body = {
                            "expected_version": 5,
                            "client_sequence": 1,
                            "output": output,
                            "artifact_refs": [],
                        }
                        committed = await mutate(
                            resumed_browser,
                            path + "/commit-output",
                            commit_body,
                            "foundation-commit",
                        )
                        assert committed.status_code == 200, committed.text
                        committed_payload = committed.json()
                        replayed_commit = await mutate(
                            resumed_browser,
                            path + "/commit-output",
                            commit_body,
                            "foundation-commit",
                        )
                        assert replayed_commit.json() == committed_payload
                        review_body = {
                            "expected_version": 6,
                            "main_answer": "I separated HTTP status from business outcome.",
                            "did_well": "I connected protocol evidence to customer impact.",
                            "structure_weakness": "The failure boundary came too late.",
                            "vague_points": "I did not name the business error envelope.",
                            "hesitation_points": "I paused before the retry example.",
                            "change_next": "Lead with the business outcome.",
                            "self_score": 3,
                        }
                        reviewed = await mutate(
                            resumed_browser,
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
                            for item in skill.latest_snapshot.manifest  # type: ignore[union-attr]
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
                        base_url="http://app.test",
                        cookies=cookies,
                    ) as final_browser:
                        notifications = await final_browser.get("/api/v1/notifications")
                        assert notifications.status_code == 200
                        notification_id = notifications.json()["items"][0]["id"]
                        first_read = await final_browser.post(
                            f"/api/v1/notifications/{notification_id}/read",
                            headers=browser_headers,
                        )
                        second_read = await final_browser.post(
                            f"/api/v1/notifications/{notification_id}/read",
                            headers=browser_headers,
                        )
                        assert first_read.status_code == second_read.status_code == 200
                        assert first_read.json()["read_at"] == second_read.json()["read_at"]
                        refreshed_today = await final_browser.get(
                            "/api/v1/today?date=2026-08-24"
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
