"""A practice answer waits for its transcript, is reviewed once, and stays the owner's."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

ANSWER = "I spent four years building the customer side and I hit the ceiling there"


class FakePracticeTransport:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def review_practice(self, request: object) -> Mapping[str, object]:
        self.requests.append(request)
        return {
            "dimensions": [
                {
                    "slug": "answer_clarity",
                    "score": "3.0",
                    "evidence": "I hit the ceiling there",
                    "note": "Direct.",
                },
                {
                    "slug": "technical_examples",
                    "score": "1.5",
                    "evidence": "building the customer side",
                    "note": "No concrete example.",
                },
                {
                    "slug": "english_accuracy",
                    "score": "3.5",
                    "evidence": "I spent four years",
                    "note": "Accurate simple past.",
                },
            ],
            "strengths": ["Opens with the four years."],
            "fixes": [
                {
                    "heard": "I hit the ceiling there",
                    "say_instead": "I hit the ceiling of what I can learn there",
                    "why": "Names what the ceiling is.",
                }
            ],
            "reference_coverage": "The scale anchor is missing.",
            "readiness": "drilling",
        }


def test_practice_answer_round_trip(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.practice_review import PracticeReviewService
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.interviews.schemas import ReferenceImportCommand
    from tamforge_backend.interviews.service import ReferenceMaterialService
    from tamforge_backend.notifications.models import BackgroundJob
    from tamforge_backend.practice.schemas import PracticeAnswerCommand
    from tamforge_backend.practice.service import (
        PRACTICE_REVIEW_JOB_KIND,
        PracticeAnswerService,
        PracticeInvalid,
        PracticeNotFound,
    )
    from tamforge_backend.recordings.models import Recording
    from tamforge_backend.speech.analysis import SpeechAnalysisService
    from tamforge_backend.speech.repository import SqlAlchemyTranscriptRepository
    from tamforge_backend.speech.service import TranscriptService
    from tamforge_backend.testing.speech import insert_stored_recording, transcript_command
    from tamforge_backend.workers.claude import practice_review_step

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
            recording_id = insert_stored_recording(
                connection, owner_id=owner_id, started_at=datetime(2026, 9, 17, 17, tzinfo=UTC)
            )

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            transport = FakePracticeTransport()
            reviewer = PracticeReviewService(transport, model="claude-fable-5-1")
            # In the past on purpose: a queued job is claimable once available_at has passed.
            now = datetime(2026, 9, 17, 17, 5, tzinfo=UTC)
            try:
                async with factory() as session:
                    imported = await ReferenceMaterialService(session).import_markdown(
                        owner_id=owner_id,
                        command=ReferenceImportCommand(
                            kind="answer_bank",
                            title="bank",
                            markdown="## Q1. Why are you leaving?\nFour anchors: years, ceiling.",
                        ),
                    )
                    entry_id = imported.entries[0].id
                wanted = PracticeAnswerCommand(
                    question="Why are you leaving?",
                    recording_id=recording_id,
                    reference_material_id=entry_id,
                )
                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    with pytest.raises(PracticeNotFound):
                        await service.submit(
                            owner_id=owner_id,
                            command=wanted.model_copy(update={"recording_id": uuid4()}),
                        )
                    with pytest.raises(PracticeInvalid):
                        await service.submit(
                            owner_id=owner_id,
                            command=wanted.model_copy(update={"reference_material_id": 999_999}),
                        )
                    # Another owner cannot claim this recording.
                    with pytest.raises(PracticeNotFound):
                        await service.submit(owner_id=other_id, command=wanted)
                    waiting = await service.submit(owner_id=owner_id, command=wanted)
                    assert waiting.status == "awaiting_transcript"
                    assert waiting.recording_id == recording_id and waiting.dimensions == ()
                # Nothing to review yet, so nothing was queued.
                assert await practice_review_step(factory, reviewer=reviewer) == 0

                # The Mac's transcript arrives: the interviewer's voice on the system track,
                # the learner's answer on the microphone.
                async with factory() as session:
                    transcripts = TranscriptService(
                        session, SqlAlchemyTranscriptRepository(session)
                    )
                    await transcripts.submit(
                        owner_id=owner_id,
                        recording_id=recording_id,
                        command=transcript_command(
                            track="system_audio", segments=[(0, 1500, "why are you leaving")]
                        ),
                    )
                    await transcripts.submit(
                        owner_id=owner_id,
                        recording_id=recording_id,
                        command=transcript_command(
                            track="microphone", segments=[(2000, 9000, ANSWER)]
                        ),
                    )
                    recording_pk = await session.scalar(
                        select(Recording.id).where(Recording.client_recording_id == recording_id)
                    )
                    await session.rollback()
                    assert recording_pk is not None
                    await SpeechAnalysisService(session).process(
                        owner_id=owner_id, recording_pk=recording_pk
                    )

                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    queued = await service.submit(owner_id=owner_id, command=wanted)
                    assert queued.status == "queued" and queued.id == waiting.id
                    again = await service.submit(owner_id=owner_id, command=wanted)
                    assert again.status == "queued"  # the key holds: one job
                assert await practice_review_step(factory, reviewer=reviewer) == 1

                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    page = await service.list(owner_id=owner_id)
                    assert len(page.items) == 1
                    ready = page.items[0]
                    assert ready.status == "ready" and ready.readiness == "drilling"
                    assert [d.slug for d in ready.dimensions] == [
                        "answer_clarity",
                        "technical_examples",
                        "english_accuracy",
                    ]
                    assert ready.dimensions[0].name == "Answer clarity and structure"
                    assert ready.dimensions[1].score == Decimal("1.5")
                    assert ready.fixes[0].heard == "I hit the ceiling there"
                    assert ready.model == "claude-fable-5-1" and ready.reviewed_at is not None
                    # Reviewed once: sending it again queues nothing and changes nothing.
                    settled = await service.submit(owner_id=owner_id, command=wanted)
                    assert settled.status == "ready"
                    jobs = await session.scalar(
                        select(func.count())
                        .select_from(BackgroundJob)
                        .where(BackgroundJob.kind == PRACTICE_REVIEW_JOB_KIND)
                    )
                    await session.rollback()
                    assert jobs == 1
                    assert (await service.list(owner_id=other_id)).items == ()

                request = transport.requests[-1]
                # Only the learner's words are the answer; the question is not evidence.
                assert request.answer_transcript == ANSWER  # type: ignore[attr-defined]
                assert "Four anchors" in request.reference_answer  # type: ignore[attr-defined]
                assert "speech_rate_wpm" in request.speech_metrics  # type: ignore[attr-defined]
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


FOLLOW_UP_ANSWER = (
    "I changed the weekly meeting into a daily checkpoint and the customer renewed for two years"
)


class FollowUpAwareTransport(FakePracticeTransport):
    async def review_practice(self, request: object) -> Mapping[str, object]:
        payload = dict(await super().review_practice(request))
        if getattr(request, "is_follow_up", False):
            payload["dimensions"] = [
                {
                    "slug": "answer_clarity",
                    "score": "3.0",
                    "evidence": "I changed the weekly meeting",
                    "note": "One change, stated first.",
                },
                {
                    "slug": "technical_examples",
                    "score": "2.5",
                    "evidence": "a daily checkpoint",
                    "note": "Concrete, no number.",
                },
                {
                    "slug": "english_accuracy",
                    "score": "3.5",
                    "evidence": "the customer renewed",
                    "note": "Accurate simple past.",
                },
                {
                    "slug": "follow_up_handling",
                    "score": "3.0",
                    "evidence": "renewed for two years",
                    "note": "Answers what was asked.",
                },
            ]
            payload["fixes"] = [
                {
                    "heard": "a daily checkpoint",
                    "say_instead": "a fifteen minute daily checkpoint",
                    "why": "A number makes it concrete.",
                }
            ]
        return payload


def test_a_follow_up_answer_is_linked_and_scored_on_handling(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.practice_review import PracticeReviewService
    from tamforge_backend.database import database_url_to_sync
    from tamforge_backend.practice.models import PracticeAnswer
    from tamforge_backend.practice.schemas import PracticeAnswerCommand
    from tamforge_backend.practice.service import PracticeAnswerService, PracticeNotFound
    from tamforge_backend.recordings.models import Recording
    from tamforge_backend.speech.analysis import SpeechAnalysisService
    from tamforge_backend.speech.repository import SqlAlchemyTranscriptRepository
    from tamforge_backend.speech.service import TranscriptService
    from tamforge_backend.testing.speech import insert_stored_recording, transcript_command
    from tamforge_backend.workers.claude import practice_review_step

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
            first_recording = insert_stored_recording(
                connection, owner_id=owner_id, started_at=datetime(2026, 9, 17, 17, tzinfo=UTC)
            )
            second_recording = insert_stored_recording(
                connection, owner_id=owner_id, started_at=datetime(2026, 9, 17, 17, 2, tzinfo=UTC)
            )

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            transport = FollowUpAwareTransport()
            reviewer = PracticeReviewService(transport, model="claude-fable-5-1")
            now = datetime(2026, 9, 17, 17, 5, tzinfo=UTC)
            first = PracticeAnswerCommand(
                question="Tell me about a difficult customer.", recording_id=first_recording
            )
            second = PracticeAnswerCommand(
                question="Tell me about a difficult customer.",
                recording_id=second_recording,
                follow_up_question="What exactly did you change?",
                follow_up_of_recording_id=first_recording,
            )

            async def transcribe(recording_id: object, said: str) -> None:
                async with factory() as session:
                    transcripts = TranscriptService(
                        session, SqlAlchemyTranscriptRepository(session)
                    )
                    await transcripts.submit(
                        owner_id=owner_id,
                        recording_id=recording_id,  # type: ignore[arg-type]
                        command=transcript_command(
                            track="microphone", segments=[(2000, 9000, said)]
                        ),
                    )
                    recording_pk = await session.scalar(
                        select(Recording.id).where(Recording.client_recording_id == recording_id)
                    )
                    await session.rollback()
                    assert recording_pk is not None
                    await SpeechAnalysisService(session).process(
                        owner_id=owner_id, recording_pk=recording_pk
                    )

            try:
                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    # The follow-up cannot arrive before the answer it followed.
                    with pytest.raises(PracticeNotFound):
                        await service.submit(owner_id=owner_id, command=second)
                    parent = await service.submit(owner_id=owner_id, command=first)
                    child = await service.submit(owner_id=owner_id, command=second)
                    assert child.follow_up_of == parent.id
                    assert child.follow_up_question == "What exactly did you change?"
                    assert parent.follow_up_of is None and parent.follow_up_question is None

                # Only the follow-up is transcribed: its review waits for the earlier answer.
                await transcribe(second_recording, FOLLOW_UP_ANSWER)
                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    waiting = await service.submit(owner_id=owner_id, command=second)
                    assert waiting.status == "awaiting_transcript"

                await transcribe(first_recording, ANSWER)
                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    for wanted in (first, second):
                        queued = await service.submit(owner_id=owner_id, command=wanted)
                        assert queued.status == "queued"
                assert await practice_review_step(factory, reviewer=reviewer) == 1
                assert await practice_review_step(factory, reviewer=reviewer) == 1

                async with factory() as session:
                    service = PracticeAnswerService(session, reviewer=reviewer, clock=lambda: now)
                    page = await service.list(owner_id=owner_id)
                    by_id = {item.id: item for item in page.items}
                    assert [d.slug for d in by_id[parent.id].dimensions] == [
                        "answer_clarity",
                        "technical_examples",
                        "english_accuracy",
                    ]
                    handled = by_id[child.id].dimensions[-1]
                    assert handled.slug == "follow_up_handling"
                    assert handled.name.startswith("Follow-up handling")
                    versions = (
                        await session.scalars(select(PracticeAnswer.prompt_version))
                    ).all()
                    await session.rollback()
                    assert set(versions) == {"v2"}

                linked = [r for r in transport.requests if getattr(r, "is_follow_up", False)]
                assert len(linked) == 1
                assert linked[0].answer_transcript == FOLLOW_UP_ANSWER  # type: ignore[attr-defined]
                assert linked[0].parent_transcript == ANSWER  # type: ignore[attr-defined]
                assert linked[0].parent_question == first.question  # type: ignore[attr-defined]
                asked = linked[0].follow_up_question  # type: ignore[attr-defined]
                assert asked == second.follow_up_question
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
