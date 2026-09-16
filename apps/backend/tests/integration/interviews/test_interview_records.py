"""Interview records on Postgres: create, edit, record with the id, attach after, list."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


def test_interview_records_and_their_recordings(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.interviews.schemas import InterviewCommand
    from tamforge_backend.interviews.service import InterviewConflict, InterviewService
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
                draft = InterviewCommand(
                    company="Acme",
                    role="TAM",
                    stage="screen",
                    starts_at=datetime(2026, 9, 20, 15, tzinfo=UTC),
                    expected_duration_minutes=45,
                    privacy_permission_code="permission_granted",
                )
                async with factory() as session:
                    service = InterviewService(session)
                    created = await service.create(owner_id=owner_id, command=draft)
                    edited = await service.update(
                        owner_id=owner_id,
                        interview_id=created.id,
                        command=draft.model_copy(update={"stage": "panel", "status": "completed"}),
                    )
                    assert edited.stage == "panel" and edited.status == "completed"

                # A recording started from the record carries the interview id.
                async with factory() as session:
                    repository = SqlAlchemyRecordingRepository(session)
                    before = create_command(uuid4())
                    linked = RecordingCreateCommand.model_validate(
                        {**before.model_dump(mode="json"), "interview_id": created.id}
                    )
                    await repository.create(
                        owner_id=owner_id,
                        command=linked,
                        idempotency_key="create-before",
                        request_hash=hashlib.sha256(b"before").digest(),
                    )
                    with pytest.raises(RecordingInvalidRequest):
                        await repository.create(
                            owner_id=owner_id,
                            command=RecordingCreateCommand.model_validate(
                                {
                                    **create_command(uuid4()).model_dump(mode="json"),
                                    "interview_id": 999,
                                }
                            ),
                            idempotency_key="create-ghost",
                            request_hash=hashlib.sha256(b"ghost").digest(),
                        )
                    # A free recording made earlier is attached after the fact.
                    free = create_command(uuid4())
                    await repository.create(
                        owner_id=owner_id,
                        command=free,
                        idempotency_key="create-after",
                        request_hash=hashlib.sha256(b"after").digest(),
                    )

                async with factory() as session:
                    service = InterviewService(session)
                    attached = await service.attach_recording(
                        owner_id=owner_id, interview_id=created.id, recording_id=free.recording_id
                    )
                    assert {r.recording_id for r in attached.recordings} == {
                        linked.recording_id,
                        free.recording_id,
                    }
                    other = await service.create(
                        owner_id=owner_id, command=draft.model_copy(update={"company": "Beta"})
                    )
                    with pytest.raises(InterviewConflict):
                        await service.attach_recording(
                            owner_id=owner_id, interview_id=other.id, recording_id=free.recording_id
                        )
                    listed = await service.list(owner_id=owner_id)
                    assert [item.company for item in listed.items] == ["Beta", "Acme"]
                    by_interview = await SqlAlchemyRecordingRepository(session).for_interview(
                        owner_id=owner_id, interview_id=created.id
                    )
                    assert len(by_interview) == 2
                    assert all(item.interview_id == created.id for item in by_interview)
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
