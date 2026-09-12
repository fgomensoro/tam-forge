"""A coaching thread on a real database: refuse before commit, answer after, accept evidence."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def respond(self, request: object) -> Mapping[str, object]:
        self.requests.append(request)
        next_step = request.next_step  # type: ignore[attr-defined]
        return {
            "message": "Your note names delivery but not retries. Add the backoff rule.",
            "next_step": next_step,
            "proposed_evidence": [{"kind": "note", "text": "Retries use exponential backoff."}],
        }


@pytest.mark.integration
def test_coach_thread_lifecycle_on_postgres(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.coach import CoachService
    from tamforge_backend.coaching.models import CoachEvidence
    from tamforge_backend.coaching.service import (
        CoachingConflict,
        CoachingInvalidRequest,
        CoachingUnavailable,
        CoachThreadService,
    )
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.learning.models import ActivityInstance, Attempt, DailyClose, StudyDay
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.roadmaps.models import TaskDefinition
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore
    from tamforge_backend.today.models import DailyHandoff

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
                            idempotency_key="coach-roadmap",
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

                # The day before closed with a gap; its handoff is what the Coach opens with.
                async with factory() as session:
                    async with transaction_scope(session):
                        closed_at = datetime(2026, 8, 23, 23, tzinfo=UTC)
                        previous = StudyDay(
                            owner_id=owner_id,
                            roadmap_version_id=approved.id,
                            local_date=closed_at.date(),
                            planned_minutes=60,
                            focused_minutes=0,
                            day_type="weekday",
                            status="planned",
                            created_at=closed_at - timedelta(hours=3),
                            started_at=None,
                            closed_at=None,
                        )
                        session.add(previous)
                        await session.flush()
                        previous.status = "in_progress"
                        previous.started_at = closed_at - timedelta(hours=2)
                        await session.flush()
                        previous.focused_minutes = 20
                        previous.status = "incomplete"
                        previous.closed_at = closed_at
                        await session.flush()
                        close = DailyClose(
                            owner_id=owner_id,
                            roadmap_version_id=approved.id,
                            study_day_id=previous.id,
                            evidence_confirmed=True,
                            evidence_manifest={"schema_version": 1},
                            strongest_output="A warm-up note.",
                            repeated_mistake="Started late.",
                            unfinished_classification="required",
                            unfinished_requirement="Finish the warm-up.",
                            correction_count=0,
                            closed_at=closed_at,
                        )
                        session.add(close)
                        await session.flush()
                        session.add(
                            DailyHandoff(
                                owner_id=owner_id,
                                study_day_id=previous.id,
                                daily_close_id=close.id,
                                local_date=previous.local_date,
                                day_status="incomplete",
                                focused_minutes=20,
                                next_action="Finish p0-w00-d00-warmup: Warm up.",
                                blocks=[],
                                gaps=["p0-w00-d00-warmup (required) left ready"],
                            )
                        )

                transport = FakeTransport()

                def service(session):  # type: ignore[no-untyped-def]
                    return CoachThreadService(
                        session, coach=CoachService(transport, model="claude-opus-5")
                    )

                async with factory() as session:
                    before = await service(session).thread(
                        owner_id=owner_id, activity_id=coached_id
                    )
                    assert before.thread_id is None and before.coaching_allowed
                    assert not before.committed
                    with pytest.raises(CoachingConflict, match="commit"):
                        await service(session).send(
                            owner_id=owner_id, activity_id=coached_id, text="ya lo hice"
                        )
                    with pytest.raises(CoachingConflict, match="does not allow"):
                        await service(session).send(
                            owner_id=owner_id, activity_id=forbidden_id, text="hola"
                        )

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
                    after = await service(session).send(
                        owner_id=owner_id, activity_id=coached_id, text="ya lo hice"
                    )
                    assert after.thread_id is not None
                    assert [m.speaker for m in after.messages] == ["learner", "coach"]
                    coach_message = after.messages[1]
                    assert coach_message.next_step == after.next_step
                    assert coach_message.proposed_evidence[0].accepted is False
                    request = transport.requests[0]
                    assert request.committed_attempt.startswith("Webhooks deliver")  # type: ignore[attr-defined]
                    assert request.block.allowed_ai_role == "tutor"  # type: ignore[attr-defined]
                    # The previous day's handoff opens the conversation; the plan's next
                    # step is still the activity's own, never the handoff's.
                    assert request.handoff is not None  # type: ignore[attr-defined]
                    assert "Next action: Finish p0-w00-d00-warmup: Warm up." in request.handoff  # type: ignore[attr-defined]
                    assert "- p0-w00-d00-warmup (required) left ready" in request.handoff  # type: ignore[attr-defined]
                    assert request.next_step == after.next_step  # type: ignore[attr-defined]

                async with factory() as session:
                    accepted = await service(session).accept_evidence(
                        owner_id=owner_id,
                        activity_id=coached_id,
                        message_id=coach_message.id,
                        index=0,
                    )
                    assert accepted.messages[1].proposed_evidence[0].accepted is True
                    again = await service(session).accept_evidence(
                        owner_id=owner_id,
                        activity_id=coached_id,
                        message_id=coach_message.id,
                        index=0,
                    )
                    assert again.messages[1].proposed_evidence[0].accepted is True
                    with pytest.raises(CoachingInvalidRequest):
                        await service(session).accept_evidence(
                            owner_id=owner_id,
                            activity_id=coached_id,
                            message_id=coach_message.id,
                            index=3,
                        )
                    count = await session.scalar(
                        select(CoachEvidence.id).where(CoachEvidence.owner_id == owner_id)
                    )
                    assert count is not None

                async with factory() as session:
                    disabled = CoachThreadService(session, coach=CoachService(None, model="m"))
                    with pytest.raises(CoachingUnavailable):
                        await disabled.send(owner_id=owner_id, activity_id=coached_id, text="más")
                    thread = await disabled.thread(owner_id=owner_id, activity_id=coached_id)
                    assert len(thread.messages) == 2
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
