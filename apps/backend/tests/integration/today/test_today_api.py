"""End-to-end Today materialization, reload, Sunday, and daily-close API."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"


def test_today_api_is_deterministic_resumable_and_sunday_safe(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.auth.dependencies import (
        get_authenticated_owner,
        require_csrf_owner,
    )
    from tamforge_backend.auth.schemas import AuthenticatedOwner
    from tamforge_backend.config import Settings
    from tamforge_backend.database import (
        database_url_to_sync,
        session_scope,
        transaction_scope,
    )
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.learning.models import ActivityInstance, DailyClose, LearnerSetting
    from tamforge_backend.main import create_app
    from tamforge_backend.notifications.models import OutboxEvent
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore
    from tamforge_backend.today.models import ActivityProcessingStatus
    from tamforge_backend.today.repository import SqlAlchemyTodayRepository
    from tamforge_backend.today.routes import get_today_service
    from tamforge_backend.today.service import TodayService

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

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(
                drivername="postgresql+asyncpg"
            )
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(
                engine,
                expire_on_commit=False,
                autoflush=False,
            )
            try:
                async with factory() as session:
                    roadmap_service = RoadmapService(
                        config=load_config_bundle(ROOT / "config"),
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=InMemoryObjectStore(),
                        mirror=None,
                    )
                    with inspect_zip_stream((FIXTURE.read_bytes(),)) as package:
                        staged = await roadmap_service.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="today-roadmap",
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

                fixed_now = datetime.now(UTC)

                owner = AuthenticatedOwner(
                    owner_id=owner_id,
                    github_user_id=102269369,
                    github_login="fgomensoro",
                    session_id=1,
                    csrf_hash=b"c" * 32,
                    expires_at=fixed_now + timedelta(hours=1),
                )
                app = create_app(
                    Settings(
                        environment="test",
                        github_user_id=102269369,
                        database_url=test_database_url,
                        cors_origins=["https://app.example.test"],
                        secure_cookies=False,
                        _env_file=None,
                    )
                )

                async def today_dependency():  # type: ignore[no-untyped-def]
                    async with session_scope(factory) as session:
                        yield TodayService(
                            SqlAlchemyTodayRepository(
                                session,
                                clock=lambda: fixed_now,
                            )
                        )

                app.dependency_overrides[get_today_service] = today_dependency
                app.dependency_overrides[get_authenticated_owner] = lambda: owner
                app.dependency_overrides[require_csrf_owner] = lambda: owner

                async with app.router.lifespan_context(app):
                    async with AsyncClient(
                        transport=ASGITransport(app=app),
                        base_url="https://app.example.test",
                    ) as client:
                        initial = await client.get(
                            "/api/v1/today?date=2026-08-24"
                        )
                        assert initial.status_code == 200, initial.text
                        initial_payload = initial.json()
                        assert initial_payload["total_planned_minutes"] == 240
                        assert len(initial_payload["tasks"]) == 7
                        assert initial_payload["primary_continue"]["kind"] == "start_activity"
                        assert initial.headers["etag"] == initial_payload["etag"]
                        first_activity_id = initial_payload["tasks"][0]["activity_id"]
                        second_activity_id = initial_payload["tasks"][1]["activity_id"]

                        async with factory() as session:
                            async with transaction_scope(session):
                                first = await session.get(
                                    ActivityInstance, first_activity_id
                                )
                                assert first is not None
                                first_started_at = first.created_at + timedelta(seconds=1)
                                first.state = "active"
                                first.started_at = first_started_at
                                first.optimistic_version += 1
                                await session.flush()
                                first.state = "output_committed"
                                first.output_committed_at = first_started_at + timedelta(minutes=1)
                                first.optimistic_version += 1
                                session.add(
                                    ActivityProcessingStatus(
                                        owner_id=owner_id,
                                        activity_instance_id=second_activity_id,
                                        state="ready",
                                        progress_label="ready",
                                        last_error_category=None,
                                        last_error_details=None,
                                        created_at=fixed_now,
                                        updated_at=fixed_now,
                                    )
                                )

                        refreshed = await client.get(
                            "/api/v1/today?date=2026-08-24"
                        )
                        assert refreshed.status_code == 200, refreshed.text
                        refreshed_payload = refreshed.json()
                        assert refreshed_payload["etag"] != initial_payload["etag"]
                        assert refreshed_payload["primary_continue"] == {
                            "kind": "complete_self_review",
                            "target_id": first_activity_id,
                            "label": "Complete mandatory self-review",
                            "allowed_ai_role": "none",
                        }
                        assert refreshed_payload["awaiting_self_reviews"][0][
                            "activity_id"
                        ] == first_activity_id
                        assert refreshed_payload["analyses"][0]["activity_id"] == second_activity_id

                        sunday = await client.get(
                            "/api/v1/today?date=2026-08-30"
                        )
                        assert sunday.status_code == 200, sunday.text
                        assert sunday.json()["day_status"] == "off"
                        assert sunday.json()["tasks"] == []
                        assert sunday.json()["total_planned_minutes"] == 0
                        assert sunday.json()["primary_continue"] is None

                        close_body = {
                            "evidence_confirmed": True,
                            "evidence_manifest": {
                                "schema_version": 1,
                                "activity_ids": [first_activity_id],
                            },
                            "strongest_output": "A saved SQL explanation with business meaning.",
                            "repeated_mistake": "The customer impact came too late.",
                            "unfinished_classification": "required",
                            "unfinished_requirement": (
                                "Complete the remaining required roadmap work."
                            ),
                            "correction_ids": [],
                        }
                        headers = {"Idempotency-Key": "close-2026-08-24"}
                        closed = await client.post(
                            "/api/v1/today/2026-08-24/close",
                            json=close_body,
                            headers=headers,
                        )
                        replayed = await client.post(
                            "/api/v1/today/2026-08-24/close",
                            json=close_body,
                            headers=headers,
                        )
                        assert closed.status_code == replayed.status_code == 200
                        assert closed.json()["day_status"] == "incomplete"
                        assert closed.json()["consequence"] == "replace_adaptive"
                        assert closed.json()["replayed"] is False
                        assert replayed.json()["replayed"] is True
                        assert (
                            closed.json()["daily_close_id"]
                            == replayed.json()["daily_close_id"]
                        )

                async with factory() as session:
                    assert await session.scalar(
                        select(func.count()).select_from(DailyClose)
                    ) == 1
                    assert await session.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.event_type == "study_day.incomplete")
                    ) == 1
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
