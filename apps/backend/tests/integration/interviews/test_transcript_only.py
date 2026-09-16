"""A transcript-only interview and the reference material, on Postgres."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
CONFIG_DIR = Path(__file__).parents[5] / "config"


class FakeDebriefTransport:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def debrief(self, request: object) -> Mapping[str, object]:
        self.requests.append(request)
        skills = [s.slug for s in request.skills]  # type: ignore[attr-defined]
        return {
            "summary": "Names the cause; says nothing about the customer's cost.",
            "strengths": [
                {"statement": "Names the cause.", "evidence": "Short.", "skill_slug": skills[0]},
                {"statement": "Stays concrete.", "evidence": "short", "skill_slug": skills[1]},
            ],
            "gaps": [
                {"statement": "No impact stated.", "evidence": "Short.", "skill_slug": skills[0]},
                {"statement": "No close.", "evidence": "short", "skill_slug": skills[1]},
            ],
            "skills_affected": [
                {"skill_slug": skills[0], "direction": "flat", "evidence": "Short."}
            ],
            "next_week_practice": [
                {
                    "description": "Retell with the cost first.",
                    "skill_slug": skills[1],
                    "minutes": 20,
                }
            ],
            "hiring_progression": "Waiting to hear back.",
        }


def test_transcript_only_interview_and_reference_import(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.debrief import DebriefService
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.evidence.seed import seed_config
    from tamforge_backend.interviews.debriefs import InterviewDebriefService
    from tamforge_backend.interviews.schemas import (
        InterviewCommand,
        InterviewTranscriptCommand,
        ReferenceImportCommand,
    )
    from tamforge_backend.interviews.service import (
        InterviewConflict,
        InterviewInvalid,
        InterviewNotFound,
        InterviewService,
        ReferenceMaterialService,
    )
    from tamforge_backend.workers.claude import debrief_step

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
                    service = InterviewService(session)
                    created = await service.create(
                        owner_id=owner_id,
                        command=InterviewCommand(
                            company="Coframe",
                            role="TAM",
                            stage="screen",
                            starts_at=datetime(2026, 9, 10, 17, tzinfo=UTC),
                            expected_duration_minutes=45,
                            status="completed",
                            privacy_permission_code="permission_granted",
                        ),
                    )
                    assert created.has_transcript is False
                    with pytest.raises(InterviewNotFound):
                        await service.transcript(owner_id=owner_id, interview_id=created.id)
                    with pytest.raises(InterviewInvalid):
                        await service.attach_transcript(
                            owner_id=owner_id,
                            interview_id=created.id,
                            command=InterviewTranscriptCommand(text="no speakers"),
                        )
                    analysis = await service.attach_transcript(
                        owner_id=owner_id,
                        interview_id=created.id,
                        command=InterviewTranscriptCommand(
                            text="Interviewer: Walk me through an escalation.\n"
                            "Frank: A payments customer saw duplicate webhooks.\n"
                            "I traced retries to the idempotency key.\n",
                            learner_labels=("Frank",),
                        ),
                    )
                    assert analysis.analysis_kind == "transcript_only"
                    assert analysis.learner_turns == 1 and analysis.other_turns == 1
                    assert "pronunciation" in analysis.excluded_findings
                    again = await service.attach_transcript(
                        owner_id=owner_id,
                        interview_id=created.id,
                        command=InterviewTranscriptCommand(
                            text="Frank: Short.\n", learner_labels=("Frank",)
                        ),
                    )
                    assert again.learner_words == 1 and again.other_turns == 0
                    read = await service.transcript(owner_id=owner_id, interview_id=created.id)
                    assert read.turns[0].text == "Short."
                    assert (
                        await service.get(owner_id=owner_id, interview_id=created.id)
                    ).has_transcript

                async with factory() as session:
                    reference = ReferenceMaterialService(session)
                    bank = ReferenceImportCommand(
                        kind="answer_bank",
                        title="Answer bank",
                        markdown="# Answer bank\n\n## Handling an escalation\nReadiness: ready\n"
                        "Duplicate webhooks; idempotency key.\n\n## Why TAM\nStatus: draft\n"
                        "Customers and systems.\n",
                    )
                    first = await reference.import_markdown(owner_id=owner_id, command=bank)
                    assert (first.created, first.existing) == (2, 0)
                    assert all(e.readiness_verified is False for e in first.entries)
                    second = await reference.import_markdown(owner_id=owner_id, command=bank)
                    assert (second.created, second.existing) == (0, 2)
                    listed = await reference.list(owner_id=owner_id, kind="answer_bank")
                    assert [e.heading for e in listed.items] == [
                        "Handling an escalation",
                        "Why TAM",
                    ]
                    cited = await reference.citations(
                        owner_id=owner_id, text="Explain the escalation with duplicate webhooks"
                    )
                    assert len(cited) == 1 and cited[0].startswith(
                        "[answer_bank] Handling an escalation"
                    )
                    assert "unverified" in cited[0]
                    await session.rollback()

                # The debrief: refused without a skill catalog, queued once it is seeded,
                # run by the worker, read back with its quotes and practice; the same
                # transcript is not debriefed twice.
                debriefer = DebriefService(FakeDebriefTransport(), model="claude-opus-5")
                async with factory() as session:
                    service = InterviewDebriefService(session, debriefer=debriefer)
                    before = await service.read(owner_id=owner_id, interview_id=created.id)
                    assert before.status == "not_requested"
                    queued = await service.request(owner_id=owner_id, interview_id=created.id)
                    assert queued.status == "queued"
                    async with transaction_scope(session):
                        await seed_config(
                            load_config_bundle(CONFIG_DIR),
                            owner_id=owner_id,
                            session=session,
                            apply=True,
                        )
                assert await debrief_step(factory, debriefer=debriefer) == 1
                async with factory() as session:
                    service = InterviewDebriefService(session, debriefer=debriefer)
                    ready = await service.read(owner_id=owner_id, interview_id=created.id)
                    assert ready.status == "ready", ready
                    assert ready.transcript_source == "transcript_only"
                    assert ready.model == "claude-opus-5"
                    assert len(ready.strengths) == 2 and len(ready.gaps) == 2
                    assert ready.skills_affected[0].skill_name
                    assert ready.next_week_practice[0].minutes == 20
                    with pytest.raises(InterviewConflict):
                        await service.request(owner_id=owner_id, interview_id=created.id)
                    transport = debriefer._transport  # type: ignore[attr-defined]
                    assert transport.requests[0].transcript_source == "transcript_only"
                    assert transport.requests[0].reference  # the answer bank was cited
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
