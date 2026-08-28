"""PostgreSQL-backed Last-Event-ID resume and cross-owner isolation tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.integration


def test_status_resume_survives_repository_restart_without_redis(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.notifications.repository import (
        SqlAlchemyNotificationRepository,
    )

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    try:
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()
            foreign_owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269370, 'foreign') RETURNING id"
                )
            ).scalar_one()
            event_ids: list[int] = []
            for index in range(3):
                event_ids.append(
                    connection.execute(
                        text(
                            "INSERT INTO outbox_events "
                            "(owner_id, aggregate_type, aggregate_id, event_type, "
                            "payload_schema_version, payload, occurred_at, published_at, "
                            "attempts, idempotency_key) VALUES "
                            "(:owner, 'activity', :subject, 'activity.feedback_ready', 1, "
                            "jsonb_build_object('schema_version', 1, 'subject_id', :subject), "
                            ":occurred, :occurred, 1, :key) RETURNING id"
                        ),
                        {
                            "owner": owner_id,
                            "subject": index + 1,
                            "occurred": datetime(2026, 8, 29, 12, index, tzinfo=UTC),
                            "key": f"owner-event-{index}",
                        },
                    ).scalar_one()
                )
            connection.execute(
                text(
                    "INSERT INTO outbox_events "
                    "(owner_id, aggregate_type, aggregate_id, event_type, "
                    "payload_schema_version, payload, occurred_at, published_at, "
                    "attempts, idempotency_key) VALUES "
                    "(:owner, 'activity', 99, 'activity.feedback_ready', 1, "
                    "jsonb_build_object('schema_version', 1, 'subject_id', 99), "
                    "now(), now(), 1, 'foreign-event')"
                ),
                {"owner": foreign_owner_id},
            )
    finally:
        sync_engine.dispose()

    async def exercise() -> None:
        engine = create_async_engine(
            make_url(test_database_url).set(drivername="postgresql+asyncpg")
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            async with factory() as first_session:
                first_repository = SqlAlchemyNotificationRepository(first_session)
                initial = await first_repository.list_status_events(
                    owner_id=owner_id,
                    after_event_id=0,
                    limit=2,
                )
            assert tuple(item.id for item in initial) == tuple(event_ids[:2])

            async with factory() as restarted_session:
                restarted_repository = SqlAlchemyNotificationRepository(restarted_session)
                resumed = await restarted_repository.list_status_events(
                    owner_id=owner_id,
                    after_event_id=initial[-1].id,
                    limit=100,
                )
                foreign = await restarted_repository.list_status_events(
                    owner_id=foreign_owner_id,
                    after_event_id=0,
                    limit=100,
                )
            assert tuple(item.id for item in resumed) == (event_ids[2],)
            assert len(foreign) == 1
            assert foreign[0].subject_id == 99
        finally:
            await engine.dispose()

    asyncio.run(exercise())
