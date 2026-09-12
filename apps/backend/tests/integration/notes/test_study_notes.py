"""A study note on a real database: Coach draft, learner edit, approval into evidence, export."""

from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"

DRAFT = {
    "title": "Webhooks: delivery and retries",
    "rule": "A 200 confirms durable acceptance, not processing.",
    "explanation": "The provider retries until it sees a 2xx.",
    "example": "Stripe retries with backoff for up to three days.",
    "misconceptions": ["A 200 means the event was processed."],
    "validated_queries": [],
    "sources": ["docs/webhooks.md"],
    "flashcards": [{"question": "What does a 200 confirm?", "answer": "Durable acceptance."}],
}


class FakeTransport:
    def __init__(self) -> None:
        self.note_requests: list[object] = []

    async def respond(self, request: object) -> Mapping[str, object]:
        raise AssertionError("the note flow never opens a coaching turn")

    async def draft_note(self, request: object) -> Mapping[str, object]:
        self.note_requests.append(request)
        return DRAFT


@pytest.mark.integration
def test_study_note_lifecycle_on_postgres(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.coach import CoachService
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.learning.models import (
        ActivityArtifactLink,
        ActivityInstance,
        Artifact,
        Attempt,
    )
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.notes.schemas import StudyNoteContent
    from tamforge_backend.notes.service import NoteConflict, NoteNotFound, StudyNoteService
    from tamforge_backend.roadmaps.models import TaskDefinition
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

        async def exercise() -> None:
            async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
            engine = create_async_engine(async_url)
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            store = InMemoryObjectStore()
            try:
                async with factory() as session:
                    roadmap = RoadmapService(
                        config=load_config_bundle(ROOT / "config"),
                        repository=SqlAlchemyRoadmapRepository(session),
                        object_store=InMemoryObjectStore(),
                        mirror=None,
                    )
                    with inspect_zip_stream((FIXTURE.read_bytes(),)) as package:
                        staged = await roadmap.stage_package(
                            owner_id=owner_id,
                            source_key="obsidian-main",
                            source_name="TAM Roadmap",
                            source_kind="obsidian",
                            package_kind="zip",
                            idempotency_key="notes-roadmap",
                            package=package,
                        )
                    approved = await roadmap.approve_import(owner_id=owner_id, import_id=staged.id)
                    await roadmap.activate_version(
                        owner_id=owner_id, version_id=approved.id, timezone="America/Los_Angeles"
                    )
                    async with session.begin():
                        await session.execute(
                            text(
                                "UPDATE learner_settings SET study_start_date = '2026-08-24' "
                                "WHERE owner_id = :owner"
                            ),
                            {"owner": owner_id},
                        )
                    day = await StudyDayService(session).ensure_current_day(
                        owner_id=owner_id, at=datetime(2026, 8, 24, 19, tzinfo=UTC)
                    )
                    assert day is not None
                    rows = (
                        await session.execute(
                            select(ActivityInstance, TaskDefinition)
                            .join(
                                TaskDefinition,
                                (TaskDefinition.owner_id == ActivityInstance.owner_id)
                                & (TaskDefinition.id == ActivityInstance.task_definition_id),
                            )
                            .where(ActivityInstance.study_day_id == day.id)
                            .order_by(ActivityInstance.id)
                        )
                    ).all()
                    coached_id = next(a.id for a, d in rows if d.allowed_ai_role == "tutor")
                    forbidden_id = next(a.id for a, d in rows if d.allowed_ai_role == "none")
                    await session.rollback()

                transport = FakeTransport()

                def service(session):  # type: ignore[no-untyped-def]
                    return StudyNoteService(
                        session,
                        coach=CoachService(transport, model="claude-opus-5"),
                        object_store=store,
                    )

                async with factory() as session:
                    with pytest.raises(NoteNotFound):
                        await service(session).get(owner_id=owner_id, activity_id=coached_id)
                    with pytest.raises(NoteConflict, match="commit"):
                        await service(session).draft(owner_id=owner_id, activity_id=coached_id)
                    with pytest.raises(NoteConflict, match="does not allow"):
                        await service(session).draft(owner_id=owner_id, activity_id=forbidden_id)

                # A block that forbids coaching still gets a note, written by the learner.
                async with factory() as session:
                    manual = await service(session).save(
                        owner_id=owner_id,
                        activity_id=forbidden_id,
                        content=StudyNoteContent(title="SQL joins", rule="Join on the key."),
                    )
                    assert manual.drafted_by == "learner" and manual.assistance == "independent"

                async with factory() as session:
                    async with transaction_scope(session):
                        activity = await session.get(ActivityInstance, coached_id)
                        assert activity is not None
                        now = activity.created_at + timedelta(seconds=1)
                        activity.state = "active"
                        activity.started_at = now
                        activity.optimistic_version += 1
                        await session.flush()
                        activity.state = "output_committed"
                        activity.attempt_kind = "attempt_a"
                        activity.output_committed_at = now
                        activity.optimistic_version += 1
                        await session.flush()
                        session.add(
                            Attempt(
                                owner_id=owner_id,
                                activity_instance_id=coached_id,
                                attempt_kind="attempt_a",
                                parent_attempt_id=None,
                                original_text="Webhooks deliver events; 200 means accepted.",
                                original_markdown=None,
                                original_sql=None,
                                audience="engineer",
                                prompt="Explain webhook delivery.",
                                assistance_mode="none",
                                commitment_hash=b"h" * 32,
                                committed_at=now,
                            )
                        )

                async with factory() as session:
                    drafted = await service(session).draft(
                        owner_id=owner_id, activity_id=coached_id
                    )
                    assert drafted.status == "draft" and drafted.drafted_by == "coach"
                    assert drafted.assistance == "coached"
                    assert drafted.assessment_status == "output_committed"
                    assert drafted.title == DRAFT["title"] and drafted.artifact_id is None
                    request = transport.note_requests[0]
                    assert request.committed_attempt.startswith("Webhooks deliver")  # type: ignore[attr-defined]

                async with factory() as session:
                    edited = await service(session).save(
                        owner_id=owner_id,
                        activity_id=coached_id,
                        content=StudyNoteContent(
                            title="Webhooks: delivery and retries (reviewed)",
                            rule=DRAFT["rule"],  # type: ignore[arg-type]
                            explanation=DRAFT["explanation"],  # type: ignore[arg-type]
                            example=DRAFT["example"],  # type: ignore[arg-type]
                            flashcards=DRAFT["flashcards"],  # type: ignore[arg-type]
                        ),
                    )
                    # The learner's edit keeps the recorded assistance; it is not retyped.
                    assert edited.assistance == "coached" and edited.drafted_by == "coach"
                    assert edited.title.endswith("(reviewed)")

                async with factory() as session:
                    approved_note = await service(session).approve(
                        owner_id=owner_id, activity_id=coached_id
                    )
                    assert approved_note.status == "approved"
                    assert approved_note.artifact_id is not None
                    assert approved_note.content_sha256 is not None
                    again = await service(session).approve(
                        owner_id=owner_id, activity_id=coached_id
                    )
                    assert again.artifact_id == approved_note.artifact_id
                    with pytest.raises(NoteConflict, match="frozen"):
                        await service(session).save(
                            owner_id=owner_id,
                            activity_id=coached_id,
                            content=StudyNoteContent(title="late edit"),
                        )
                    with pytest.raises(NoteConflict, match="frozen"):
                        await service(session).draft(owner_id=owner_id, activity_id=coached_id)

                async with factory() as session:
                    artifact = await session.get(Artifact, approved_note.artifact_id)
                    assert artifact is not None
                    assert artifact.artifact_class == "recall_note"
                    assert artifact.content_type == "text/markdown"
                    assert artifact.original_filename.endswith("retries reviewed.md")
                    stored = await store.stat(artifact.object_key)
                    assert stored is not None and stored.sha256 == approved_note.content_sha256
                    link = await session.scalar(
                        select(ActivityArtifactLink)
                        .where(ActivityArtifactLink.owner_id == owner_id)
                        .where(ActivityArtifactLink.artifact_id == artifact.id)
                    )
                    assert link is not None and link.activity_instance_id == coached_id

                async with factory() as session:
                    found = await service(session).search(owner_id=owner_id, query="acceptance")
                    assert [item.id for item in found.items] == [approved_note.id]
                    assert found.items[0].flashcard_count == 1
                    everything = await service(session).search(owner_id=owner_id, query="")
                    assert {item.status for item in everything.items} == {"draft", "approved"}
                    nothing = await service(session).search(owner_id=owner_id, query="100%_x")
                    assert nothing.items == []

                async with factory() as session:
                    payload = await service(session).export(
                        owner_id=owner_id, since=None, until=None
                    )
                    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                        names = sorted(archive.namelist())
                        assert len(names) == 2 and all(
                            n.startswith("notes/2026-08-24 - ") for n in names
                        )
                        exported = archive.read(next(n for n in names if "reviewed" in n)).decode(
                            "utf-8"
                        )
                    assert exported.startswith(
                        "---\ntype: polished-study-note\nstatus: validated\n"
                    )
                    assert "assistance: coached" in exported
                    assert "flashcard-source: true" in exported
                    assert hashlib.sha256(exported.encode("utf-8")).hexdigest() == (
                        approved_note.content_sha256
                    )
                    later = await service(session).export(owner_id=owner_id, since=None, until=None)
                    assert later == payload
                    outside = await service(session).export(
                        owner_id=owner_id, since=datetime(2026, 9, 1).date(), until=None
                    )
                    with zipfile.ZipFile(io.BytesIO(outside)) as archive:
                        assert archive.namelist() == []
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
