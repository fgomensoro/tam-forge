"""Concurrent transactional outbox delivery and owner-isolation tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

pytestmark = pytest.mark.integration


def test_outbox_delivery_is_exactly_once_actionable_and_owner_scoped(
    test_database_url: str,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.notifications.models import Notification, OutboxEvent
    from tamforge_backend.notifications.repository import (
        SqlAlchemyNotificationRepository,
    )
    from tamforge_backend.notifications.service import NotificationNotFound

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    saturday = datetime(2026, 8, 30, 2, tzinfo=UTC)
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
            connection.execute(
                text(
                    "INSERT INTO learner_settings "
                    "(owner_id, timezone, study_start_date) "
                    "VALUES (:owner, 'America/Los_Angeles', :start_date)"
                ),
                {"owner": owner_id, "start_date": date(2026, 8, 24)},
            )
            events = (
                ("activity", "activity.feedback_ready", 11),
                ("correction", "correction.due", 12),
                ("interview", "interview.upcoming", 13),
                ("study_day", "study_day.saturday_assessment", 14),
                (
                    "processing_status",
                    "processing_status.needs_attention",
                    15,
                ),
                ("activity", "evidence.recorded", 16),
            )
            for index, (aggregate, event_type, subject_id) in enumerate(events):
                connection.execute(
                    text(
                        "INSERT INTO outbox_events "
                        "(owner_id, aggregate_type, aggregate_id, event_type, "
                        "payload_schema_version, payload, occurred_at, attempts, "
                        "idempotency_key) VALUES "
                        "(:owner, :aggregate, :subject, :event_type, 1, "
                        "jsonb_build_object('schema_version', 1, 'subject_id', :subject), "
                        ":occurred_at, 0, :key)"
                    ),
                    {
                        "owner": owner_id,
                        "aggregate": aggregate,
                        "subject": subject_id,
                        "event_type": event_type,
                        "occurred_at": saturday,
                        "key": f"event-{index}",
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO outbox_events "
                    "(owner_id, aggregate_type, aggregate_id, event_type, "
                    "payload_schema_version, payload, occurred_at, attempts, "
                    "idempotency_key) VALUES "
                    "(:owner, 'correction', 17, 'correction.due', 1, "
                    "jsonb_build_object('schema_version', 1, 'subject_id', 17), "
                    "TIMESTAMPTZ '2026-08-30 18:00:00+00', 0, 'event-sunday')"
                ),
                {"owner": owner_id},
            )
    finally:
        sync_engine.dispose()

    async def exercise() -> None:
        engine = create_async_engine(
            make_url(test_database_url).set(drivername="postgresql+asyncpg")
        )
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        delivered_at = datetime(2026, 8, 31, 12, tzinfo=UTC)

        async def deliver():  # type: ignore[no-untyped-def]
            async with factory() as session:
                return await SqlAlchemyNotificationRepository(
                    session,
                    clock=lambda: delivered_at,
                ).deliver_outbox(limit=100)

        try:
            first, second = await asyncio.gather(deliver(), deliver())
            notification_ids = first.notification_ids + second.notification_ids
            published_ids = first.published_event_ids + second.published_event_ids
            assert len(notification_ids) == 5
            assert len(set(notification_ids)) == 5
            assert len(published_ids) == 7
            assert len(set(published_ids)) == 7
            assert (await deliver()).published_event_ids == ()

            async with factory() as session:
                assert await session.scalar(
                    select(func.count()).select_from(Notification)
                ) == 5
                assert await session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .where(OutboxEvent.published_at.is_not(None))
                    .where(OutboxEvent.attempts == 1)
                ) == 7
                item = (
                    await session.scalars(
                        select(Notification)
                        .where(Notification.owner_id == owner_id)
                        .order_by(Notification.id)
                        .limit(1)
                    )
                ).one()

            async with factory() as session:
                repository = SqlAlchemyNotificationRepository(
                    session,
                    clock=lambda: delivered_at,
                )
                first_read = await repository.mark_read(
                    owner_id=owner_id,
                    notification_id=item.id,
                )
                second_read = await repository.mark_read(
                    owner_id=owner_id,
                    notification_id=item.id,
                )
                assert first_read.read_at == second_read.read_at
                with pytest.raises(NotificationNotFound):
                    await repository.mark_read(
                        owner_id=foreign_owner_id,
                        notification_id=item.id,
                    )
        finally:
            await engine.dispose()

    asyncio.run(exercise())
