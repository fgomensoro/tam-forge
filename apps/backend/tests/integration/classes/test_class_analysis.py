"""An English class with a transcribed recording is analysed; the next class compares with it."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration


class FakeClassTransport:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def analyse_class(self, request: object) -> Mapping[str, object]:
        self.requests.append(request)
        previous = request.previous  # type: ignore[attr-defined]
        return {
            "fluency": {
                "score": "3.0" if previous else "2.5",
                "rationale": "Keeps going.",
                "evidence": "I have worked on the runbook",
            },
            "vocabulary": {"score": "2.5", "rationale": "Precise.", "evidence": "runbook"},
            "recurring_errors": [
                {
                    "pattern": "present perfect for finished past",
                    "example": "I have worked on the runbook",
                    "correction": "I worked on the runbook",
                }
            ],
            "progress_direction": "up" if previous else "first_class",
            "progress_statement": "Half a point up." if previous else "First class on record.",
            "next_focus": "Simple past narration.",
        }


def test_class_analysis_round_trip(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.class_analysis import ClassAnalysisService
    from tamforge_backend.classes.analysis import EnglishClassAnalysisService
    from tamforge_backend.classes.schemas import EnglishClassCommand
    from tamforge_backend.classes.service import ClassConflict, ClassInvalid, EnglishClassService
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.progress.service import ProgressQueryService
    from tamforge_backend.recordings.models import Recording
    from tamforge_backend.speech.analysis import SpeechAnalysisService
    from tamforge_backend.speech.repository import SqlAlchemyTranscriptRepository
    from tamforge_backend.speech.service import TranscriptService
    from tamforge_backend.testing.speech import insert_stored_recording, transcript_command
    from tamforge_backend.workers.claude import class_analysis_step

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
            transport = FakeClassTransport()
            analyst = ClassAnalysisService(transport, model="claude-fable-5-1")
            try:
                async with factory() as session:
                    classes = EnglishClassService(session)
                    first = await classes.create(
                        owner_id=owner_id,
                        command=EnglishClassCommand(
                            teacher="Maria",
                            starts_at=datetime(2026, 9, 11, 18, tzinfo=UTC),
                            expected_duration_minutes=60,
                            notes="Past tense.",
                        ),
                    )
                    second = await classes.create(
                        owner_id=owner_id,
                        command=EnglishClassCommand(
                            teacher="Maria",
                            starts_at=datetime(2026, 9, 18, 18, tzinfo=UTC),
                            expected_duration_minutes=60,
                            notes="",
                        ),
                    )
                    service = EnglishClassAnalysisService(session, analyst=analyst)
                    with pytest.raises(ClassInvalid):
                        await service.request(owner_id=owner_id, class_id=first.id)

                # Each class gets a stored recording whose transcript the server analysed.
                with sync_engine.begin() as connection:
                    recordings = {
                        record.id: insert_stored_recording(
                            connection,
                            owner_id=owner_id,
                            started_at=record.starts_at,
                            english_class_id=record.id,
                        )
                        for record in (first, second)
                    }
                for record in (first, second):
                    async with factory() as session:
                        transcripts = TranscriptService(
                            session, SqlAlchemyTranscriptRepository(session)
                        )
                        await transcripts.submit(
                            owner_id=owner_id,
                            recording_id=recordings[record.id],
                            command=transcript_command(
                                track="system_audio",
                                segments=[(0, 1500, "how was your week")],
                            ),
                        )
                        await transcripts.submit(
                            owner_id=owner_id,
                            recording_id=recordings[record.id],
                            command=transcript_command(
                                track="microphone",
                                segments=[(2000, 6000, "I have worked on the runbook")],
                            ),
                        )
                        recording_pk = await session.scalar(
                            select(Recording.id).where(
                                Recording.client_recording_id == recordings[record.id]
                            )
                        )
                        await session.rollback()
                        assert recording_pk is not None
                        await SpeechAnalysisService(session).process(
                            owner_id=owner_id, recording_pk=recording_pk
                        )

                async with factory() as session:
                    service = EnglishClassAnalysisService(session, analyst=analyst)
                    queued = await service.request(owner_id=owner_id, class_id=first.id)
                    assert queued.status == "queued"
                assert await class_analysis_step(factory, analyst=analyst) == 1
                async with factory() as session:
                    service = EnglishClassAnalysisService(session, analyst=analyst)
                    ready = await service.read(owner_id=owner_id, class_id=first.id)
                    assert ready.status == "ready", ready
                    assert ready.progress_direction == "first_class"
                    assert ready.fluency is not None and ready.fluency.score == Decimal("2.5")
                    assert ready.previous_classes == 0
                    with pytest.raises(ClassConflict):
                        await service.request(owner_id=owner_id, class_id=first.id)
                    await service.request(owner_id=owner_id, class_id=second.id)
                assert await class_analysis_step(factory, analyst=analyst) == 1
                async with factory() as session:
                    service = EnglishClassAnalysisService(session, analyst=analyst)
                    later = await service.read(owner_id=owner_id, class_id=second.id)
                    assert later.status == "ready" and later.progress_direction == "up"
                    assert later.previous_classes == 1
                    request = transport.requests[-1]
                    assert [p.fluency_score for p in request.previous] == [Decimal("2.5")]  # type: ignore[attr-defined]
                    assert "speech_rate_wpm" in request.speech_metrics  # type: ignore[attr-defined]
                    assert request.vocabulary_metrics["learner_words"] == 6  # type: ignore[attr-defined]
                    progress = await ProgressQueryService(session).read(owner_id=owner_id)
                    assert [p.fluency_score for p in progress.english_classes] == [
                        Decimal("2.5"),
                        Decimal("3.0"),
                    ]
                    assert progress.english_classes[1].progress_direction == "up"
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
