"""Cards on Postgres: created without duplicates, due by date, graded and rescheduled, exported."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


def test_cards_round_trip(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.cards.schemas import CardCommand
    from tamforge_backend.cards.service import CardInvalid, CardNotFound, CardService
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.recordings.repository import SqlAlchemyRecordingRepository
    from tamforge_backend.testing.recordings import create_command

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
            other_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (7, 'someone') RETURNING id"
                )
            ).scalar_one()
            west_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (8, 'westcoast') RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO learner_settings (owner_id, timezone, study_start_date) "
                    "VALUES (:owner, 'America/Los_Angeles', '2026-09-01')"
                ),
                {"owner": west_id},
            )

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            clock = lambda: datetime(2026, 9, 16, 12, tzinfo=UTC)  # noqa: E731
            try:
                first = CardCommand(
                    question="What does 200 from ingest mean?",
                    answer="Durably accepted, not processed.",
                    skill_slug="api_contracts",
                    source_kind="study_note",
                    source_ref="note:1",
                )
                async with factory() as session:
                    service = CardService(session, clock=clock)
                    created = await service.create(owner_id=owner_id, command=first)
                    assert created.due_on == date(2026, 9, 16)
                    assert created.scheduler_version == "sm2-v1"
                # 03:00 UTC on the 18th is the evening of the 17th in Los Angeles: the card is
                # due on the date the learner is living in, the one the app asks with.
                async with factory() as session:
                    late = CardService(
                        session, clock=lambda: datetime(2026, 9, 18, 3, 0, tzinfo=UTC)
                    )
                    evening = await late.create(
                        owner_id=west_id,
                        command=first.model_copy(update={"source_ref": "note:west"}),
                    )
                    assert evening.due_on == date(2026, 9, 17)
                    due_tonight = await late.due(owner_id=west_id, local_date=date(2026, 9, 17))
                    assert [item.id for item in due_tonight.items] == [evening.id]
                    again = await service.create(
                        owner_id=owner_id,
                        command=first.model_copy(
                            update={
                                "question": "  what does 200 FROM ingest mean? ",
                                "source_ref": "note:2",
                            }
                        ),
                    )
                    assert again.id == created.id and again.source_ref == "note:1"
                    batch = await service.create_many(
                        owner_id=owner_id,
                        commands=[
                            first,
                            first.model_copy(update={"question": "What is idempotency?"}),
                        ],
                    )
                    assert [item.id for item in batch][0] == created.id
                    assert len({item.id for item in batch}) == 2
                    foreign = await service.create(owner_id=other_id, command=first)
                    assert foreign.id != created.id

                async with factory() as session:
                    service = CardService(session, clock=clock)
                    due = await service.due(owner_id=owner_id, local_date=date(2026, 9, 16))
                    assert len(due.items) == 2
                    earlier = await service.due(owner_id=owner_id, local_date=date(2026, 9, 15))
                    assert earlier.items == ()
                    result = await service.review(
                        owner_id=owner_id,
                        card_id=created.id,
                        grade=4,
                        reviewed_on=date(2026, 9, 16),
                    )
                    assert result.card.due_on == date(2026, 9, 17)
                    assert result.review.interval_before == 0
                    assert result.review.interval_after == 1
                    with pytest.raises(CardNotFound):
                        await service.review(
                            owner_id=other_id,
                            card_id=created.id,
                            grade=4,
                            reviewed_on=date(2026, 9, 16),
                        )
                    with pytest.raises(CardInvalid):
                        await service.review(
                            owner_id=owner_id,
                            card_id=created.id,
                            grade=4,
                            reviewed_on=date(2026, 9, 17),
                            mode="spoken",
                        )

                async with factory() as session:
                    recording = create_command(uuid4())
                    await SqlAlchemyRecordingRepository(session).create(
                        owner_id=owner_id,
                        command=recording,
                        idempotency_key="card-spoken",
                        request_hash=hashlib.sha256(b"spoken").digest(),
                    )
                async with factory() as session:
                    service = CardService(session, clock=clock)
                    spoken = await service.review(
                        owner_id=owner_id,
                        card_id=created.id,
                        grade=5,
                        reviewed_on=date(2026, 9, 17),
                        mode="spoken",
                        recording_id=recording.recording_id,
                    )
                    assert spoken.review.mode == "spoken"
                    assert spoken.card.interval_days == 6
                    assert spoken.card.due_on == date(2026, 9, 23)
                    with pytest.raises(CardNotFound):
                        await service.review(
                            owner_id=other_id,
                            card_id=foreign.id,
                            grade=5,
                            reviewed_on=date(2026, 9, 17),
                            mode="spoken",
                            recording_id=recording.recording_id,
                        )
                    due_later = await service.due(owner_id=owner_id, local_date=date(2026, 9, 17))
                    assert [item.id for item in due_later.items] == [batch[1].id]
                    exported = await service.export(owner_id=owner_id)
                    assert len(exported.cards) == 2 and len(exported.reviews) == 2
                    assert [item.grade for item in exported.reviews] == [4, 5]
                    assert exported.reviews[1].card_id == created.id
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
