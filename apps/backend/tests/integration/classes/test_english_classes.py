"""English classes on Postgres: create, edit, record with the id, attach after, list."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


def test_english_classes_and_their_recordings(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.classes.schemas import EnglishClassCommand
    from tamforge_backend.classes.service import ClassConflict, EnglishClassService
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.recordings.repository import SqlAlchemyRecordingRepository
    from tamforge_backend.recordings.schemas import RecordingCreateCommand
    from tamforge_backend.recordings.service import RecordingInvalidRequest
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

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            try:
                draft = EnglishClassCommand(
                    teacher="Maria",
                    starts_at=datetime(2026, 9, 18, 18, tzinfo=UTC),
                    expected_duration_minutes=60,
                    notes="Conditionals.",
                )
                async with factory() as session:
                    service = EnglishClassService(session)
                    created = await service.create(owner_id=owner_id, command=draft)
                    assert created.skill_slug == "tam_english"
                    edited = await service.update(
                        owner_id=owner_id,
                        class_id=created.id,
                        command=draft.model_copy(update={"notes": "Pacing."}),
                    )
                    assert edited.notes == "Pacing."

                async with factory() as session:
                    repository = SqlAlchemyRecordingRepository(session)
                    linked = RecordingCreateCommand.model_validate(
                        {
                            **create_command(uuid4()).model_dump(mode="json"),
                            "english_class_id": created.id,
                        }
                    )
                    await repository.create(
                        owner_id=owner_id,
                        command=linked,
                        idempotency_key="class-before",
                        request_hash=hashlib.sha256(b"before").digest(),
                    )
                    with pytest.raises(RecordingInvalidRequest):
                        await repository.create(
                            owner_id=owner_id,
                            command=RecordingCreateCommand.model_validate(
                                {
                                    **create_command(uuid4()).model_dump(mode="json"),
                                    "english_class_id": 999,
                                }
                            ),
                            idempotency_key="class-ghost",
                            request_hash=hashlib.sha256(b"ghost").digest(),
                        )
                    free = create_command(uuid4())
                    await repository.create(
                        owner_id=owner_id,
                        command=free,
                        idempotency_key="class-after",
                        request_hash=hashlib.sha256(b"after").digest(),
                    )

                async with factory() as session:
                    service = EnglishClassService(session)
                    attached = await service.attach_recording(
                        owner_id=owner_id, class_id=created.id, recording_id=free.recording_id
                    )
                    assert {r.recording_id for r in attached.recordings} == {
                        linked.recording_id,
                        free.recording_id,
                    }
                    other = await service.create(
                        owner_id=owner_id, command=draft.model_copy(update={"teacher": "Ana"})
                    )
                    with pytest.raises(ClassConflict):
                        await service.attach_recording(
                            owner_id=owner_id, class_id=other.id, recording_id=free.recording_id
                        )
                    listed = await service.list(owner_id=owner_id)
                    assert [item.teacher for item in listed.items] == ["Ana", "Maria"]
                    by_class = await SqlAlchemyRecordingRepository(session).for_class(
                        owner_id=owner_id, class_id=created.id
                    )
                    assert len(by_class) == 2
                    assert all(item.english_class_id == created.id for item in by_class)
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
