from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"


def test_activity_commands_survive_new_api_clients_and_never_double_count(
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
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.learning.models import (
        ActivityInstance,
        ActivityTimerSession,
        LearnerSetting,
    )
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.learning.routes import get_activity_service
    from tamforge_backend.learning.service import ActivityService
    from tamforge_backend.main import create_app
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
            clock = {"now": datetime(2026, 8, 24, 19, tzinfo=UTC)}
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
                            idempotency_key="activity-command-roadmap",
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
                    activity_id = day.activity_ids[0]
                    superseded_activity_id = day.activity_ids[1]
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
                        )

                app.dependency_overrides[get_activity_service] = service_dependency
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
                    idempotency_key="start-activity-1",
                )
                assert status == 200
                assert started["state"] == "active"
                assert started["optimistic_version"] == 2

                clock["now"] += timedelta(seconds=10)
                status, first_heartbeat = await request(
                    "POST",
                    path + "/heartbeat",
                    json={"expected_version": 2, "client_sequence": 1},
                    idempotency_key="heartbeat-activity-1",
                )
                assert status == 200
                assert first_heartbeat["activity_focused_seconds"] == 10

                clock["now"] += timedelta(seconds=15)
                status, duplicate_heartbeat = await request(
                    "POST",
                    path + "/heartbeat",
                    json={"expected_version": 2, "client_sequence": 1},
                    idempotency_key="heartbeat-activity-1",
                )
                assert status == 200
                assert duplicate_heartbeat == first_heartbeat

                status, reloaded = await request("GET", path)
                assert status == 200
                assert reloaded["activity_focused_seconds"] == 10
                assert reloaded["open_timer"]["last_client_sequence"] == 1  # type: ignore[index]

                status, stale = await request(
                    "POST",
                    path + "/heartbeat",
                    json={"expected_version": 1, "client_sequence": 2},
                    idempotency_key="stale-heartbeat-activity-1",
                )
                assert status == 409
                assert stale["code"] == "activity_state_conflict"

                clock["now"] += timedelta(seconds=5)
                status, paused = await request(
                    "POST",
                    path + "/pause",
                    json={"expected_version": 2, "client_sequence": 2},
                    idempotency_key="pause-activity-1",
                )
                assert status == 200
                assert paused["state"] == "paused"
                assert paused["activity_focused_seconds"] == 30
                assert paused["open_timer"] is None

                clock["now"] += timedelta(seconds=10)
                status, reused_timer_key = await request(
                    "POST",
                    path + "/resume",
                    json={"expected_version": 3},
                    idempotency_key="start-activity-1",
                )
                assert status == 409
                assert reused_timer_key["code"] == "activity_state_conflict"

                status, resumed = await request(
                    "POST",
                    path + "/resume",
                    json={"expected_version": 3},
                    idempotency_key="resume-activity-1",
                )
                assert status == 200
                assert resumed["state"] == "active"
                assert resumed["optimistic_version"] == 4
                assert resumed["activity_focused_seconds"] == 30

                clock["now"] += timedelta(seconds=10)
                status, incomplete = await request(
                    "POST",
                    path + "/classify-incomplete",
                    json={"expected_version": 4, "classification": "useful"},
                    idempotency_key="incomplete-activity-1",
                )
                assert status == 200
                assert incomplete["state"] == "incomplete"
                assert incomplete["classification"] == "useful"
                assert incomplete["activity_focused_seconds"] == 40
                assert incomplete["open_timer"] is None

                async with factory() as verification_session:
                    activity = await verification_session.get(
                        ActivityInstance,
                        activity_id,
                    )
                    assert activity is not None
                    assert activity.state == "incomplete"
                    assert activity.optimistic_version == 5
                    assert activity.classification == "useful"
                    timers = tuple(
                        (
                            await verification_session.execute(
                                select(ActivityTimerSession)
                                .where(ActivityTimerSession.activity_instance_id == activity_id)
                                .order_by(ActivityTimerSession.id)
                            )
                        ).scalars()
                    )
                    assert len(timers) == 2
                    assert sum(timer.counted_seconds for timer in timers) == 40
                    assert all(timer.ended_at is not None for timer in timers)
                    assert (
                        await verification_session.scalar(
                            select(func.count())
                            .select_from(ActivityTimerSession)
                            .where(ActivityTimerSession.ended_at.is_(None))
                        )
                    ) == 0

                superseded_path = f"/api/v1/activities/{superseded_activity_id}"
                status, _ = await request(
                    "POST",
                    superseded_path + "/start",
                    json={"expected_version": 1},
                    idempotency_key="start-superseded-activity",
                )
                assert status == 200
                clock["now"] += timedelta(seconds=5)
                status, superseded = await request(
                    "POST",
                    superseded_path + "/classify-incomplete",
                    json={
                        "expected_version": 2,
                        "classification": "superseded",
                        "stronger_evidence_id": activity_id,
                    },
                    idempotency_key="classify-superseded-activity",
                )
                assert status == 200
                assert superseded["classification"] == "superseded"
                assert superseded["stronger_evidence_id"] == activity_id
                async with factory() as verification_session:
                    superseded_activity = await verification_session.get(
                        ActivityInstance,
                        superseded_activity_id,
                    )
                    assert superseded_activity is not None
                    assert superseded_activity.stronger_evidence_activity_id == activity_id
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
