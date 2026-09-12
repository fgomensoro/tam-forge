# ruff: noqa: E501
"""A scheme package drives Today: its own budgets, its own rest days, any start date."""

from __future__ import annotations

import asyncio
import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[5]

WEEK = "Week 1.md"
FILES: dict[str, bytes] = {
    WEEK: b"# Week 1\n\n## Day 1\n\nDo it.\n\n## Day 2\n\nAgain.\n\n## Day 3\n\nOnce more.\n",
    "docs/Queue.md": b"# Queue\n\n## P1-Q01\n\nTell me about yourself.\n",
}
SCHEME = """
schema_version: 1
program: {key: demo, title: Demo}
rest_weekdays: [saturday, sunday]
days:
  - id: d01
    kind: weekday
    budget_minutes: 180
    blocks:
      - {id: d01-interview, type: communication, minutes: 60, source: {file: docs/Queue.md, heading: P1-Q01}, objective: Answer P1-Q01.}
      - {id: d01-pipeline, type: pipeline, minutes: 30, source: {file: Week 1.md, heading: Day 1}, objective: One application.}
      - {id: d01-learning, type: technical, minutes: 75, source: {file: Week 1.md, heading: Day 1}, objective: Read the day.}
      - {id: d01-close, type: close, minutes: 15, source: {file: Week 1.md, heading: Day 1}, objective: Close the day.}
  - id: d02
    kind: assessment
    budget_minutes: 90
    blocks:
      - {id: d02-sql, type: saturday_sql, minutes: 90, source: {file: Week 1.md, heading: Day 2}, objective: Assess.}
  - id: d03
    kind: weekday
    budget_minutes: 120
    blocks:
      - {id: d03-learning, type: technical, minutes: 105, source: {file: Week 1.md, heading: Day 3}, objective: Read the day.}
      - {id: d03-close, type: close, minutes: 15, source: {file: Week 1.md, heading: Day 3}, objective: Close the day.}
"""


def _package() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(FILES):
            archive.writestr(name, FILES[name])
        archive.writestr("roadmap.yaml", SCHEME.encode("utf-8"))
    return buffer.getvalue()


@pytest.mark.integration
def test_scheme_package_drives_today_with_its_own_budgets_and_rest_days(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.auth.dependencies import get_authenticated_owner, require_csrf_owner
    from tamforge_backend.auth.schemas import AuthenticatedOwner
    from tamforge_backend.config import Settings
    from tamforge_backend.database import database_url_to_sync, session_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.main import create_app
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore
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
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            try:
                async with factory() as session:
                    roadmap_service = RoadmapService(
                        config=load_config_bundle(ROOT / "config"),
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=InMemoryObjectStore(),
                        mirror=None,
                    )
                    with inspect_zip_stream((_package(),)) as package:
                        staged = await roadmap_service.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="Demo",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="scheme-roadmap",
                            package=package,
                        )
                    assert staged.status == "validated", staged.validation_report
                    assert staged.validation_report["scheme_summary"] == {
                        "program": "Demo",
                        "study_days": 3,
                        "budget_minutes": {"1": 180, "2": 90, "3": 120},
                    }
                    approved = await roadmap_service.approve_import(
                        owner_id=owner_id, import_id=staged.id
                    )
                    # A Wednesday start: nothing in the calendar walk needs a Monday.
                    await roadmap_service.activate_version(
                        owner_id=owner_id,
                        version_id=approved.id,
                        timezone="America/Montevideo",
                    )
                    async with session.begin():
                        await session.execute(
                            text(
                                "UPDATE learner_settings SET study_start_date = :start "
                                "WHERE owner_id = :owner"
                            ),
                            {"start": date(2026, 9, 9), "owner": owner_id},
                        )
                fixed_now = datetime(2026, 9, 9, 15, tzinfo=UTC)
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
                            SqlAlchemyTodayRepository(session, clock=lambda: fixed_now)
                        )

                app.dependency_overrides[get_today_service] = today_dependency
                app.dependency_overrides[get_authenticated_owner] = lambda: owner
                app.dependency_overrides[require_csrf_owner] = lambda: owner
                async with app.router.lifespan_context(app):
                    async with AsyncClient(
                        transport=ASGITransport(app=app), base_url="https://app.example.test"
                    ) as client:
                        first = await client.get("/api/v1/today?date=2026-09-09")
                        assert first.status_code == 200, first.text
                        payload = first.json()
                        assert payload["day_type"] == "weekday"
                        assert payload["total_planned_minutes"] == 180
                        assert [task["stable_id"] for task in payload["tasks"]] == [
                            "d01-interview",
                            "d01-pipeline",
                            "d01-learning",
                            "d01-close",
                        ]
                        assert payload["time_policy"]["target_minutes"] == 180
                        assert payload["time_policy"]["acceptable_minimum"] == 165
                        assert payload["time_policy"]["hard_stop_minutes"] == 195

                        second = await client.get("/api/v1/today?date=2026-09-10")
                        assert second.status_code == 200, second.text
                        assert second.json()["day_type"] == "saturday"
                        assert second.json()["total_planned_minutes"] == 90
                        assert second.json()["time_policy"]["hard_stop_minutes"] == 90

                        third = await client.get("/api/v1/today?date=2026-09-11")
                        assert third.status_code == 200, third.text
                        assert third.json()["total_planned_minutes"] == 120

                        # Saturday and Sunday are rest days in this scheme.
                        for off in ("2026-09-12", "2026-09-13"):
                            rest = await client.get(f"/api/v1/today?date={off}")
                            assert rest.status_code == 200, rest.text
                            assert rest.json()["day_status"] == "off"
                            assert rest.json()["tasks"] == []
                        # Beyond the scheme there is no task, and Today says so.
                        beyond = await client.get("/api/v1/today?date=2026-09-14")
                        assert beyond.status_code == 404, beyond.text
            finally:
                await engine.dispose()

        asyncio.run(exercise())
    finally:
        with sync_engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        sync_engine.dispose()
