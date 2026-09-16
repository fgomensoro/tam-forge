"""A self-reviewed attempt is queued, scored, recorded as evidence, and read back."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[5]
FIXTURE = ROOT / "apps" / "backend" / "tests" / "fixtures" / "roadmaps" / "month-v1.zip"
CONFIG_DIR = ROOT / "config"


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def review(self, request: object) -> Mapping[str, object]:
        self.requests.append(request)
        dims = request.dimensions  # type: ignore[attr-defined]
        return {
            "verdict": "Correct on delivery, silent on retries.",
            "dimensions": [
                {
                    "slug": d.slug,
                    "score": "3",
                    "rationale": "Names the rule.",
                    "evidence": "200 means",
                }
                for d in dims
            ],
            "strengths": [
                {"statement": "Names durable acceptance."},
                {"statement": "Clear order."},
            ],
            "corrections": [
                {"statement": "Name the retry policy.", "instruction": "State backoff and jitter."},
                {"statement": "Close with a decision.", "instruction": "End with the next action."},
            ],
            "next_practice": "Answer the same prompt aloud in ninety seconds.",
        }


@pytest.mark.integration
def test_review_pipeline_on_postgres(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.reviewer import ReviewerService
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.evidence.models import Competency, SkillEvidenceEvent
    from tamforge_backend.evidence.repository import SqlAlchemyEvidenceRepository
    from tamforge_backend.evidence.seed import seed_config
    from tamforge_backend.learning.models import ActivityInstance, Attempt, SelfReview
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.notifications.models import OutboxEvent
    from tamforge_backend.progress.service import ProgressQueryService
    from tamforge_backend.reviews.models import ActivityReview
    from tamforge_backend.reviews.service import ReviewService
    from tamforge_backend.roadmaps.models import TaskDefinition
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore
    from tamforge_backend.today.models import ActivityProcessingStatus
    from tamforge_backend.workers.claude import review_step

    config = Config("apps/backend/alembic.ini")
    config.attributes["database_url"] = test_database_url
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    bundle = load_config_bundle(CONFIG_DIR)
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
                    async with transaction_scope(session):
                        await seed_config(bundle, owner_id=owner_id, session=session, apply=True)
                    roadmap = RoadmapService(
                        config=bundle,
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
                            idempotency_key="review-roadmap",
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
                    activity, definition = next(
                        (a, d)
                        for a, d in rows
                        if d.exercise_type
                        and d.exercise_type in {e.slug for e in bundle.exercise_types}
                    )
                    activity_id, exercise_type = activity.id, str(definition.exercise_type)
                    await session.rollback()

                # Commit an attempt and its self-review the way the workspace does.
                async with factory() as session:
                    async with transaction_scope(session):
                        row = await session.get(ActivityInstance, activity_id)
                        assert row is not None
                        # Real clocks: rows are created now, and the review must not judge
                        # evidence from the future, so every timestamp is "now".
                        now = datetime.now(UTC)
                        row.state = "active"
                        row.started_at = now
                        row.optimistic_version += 1
                        await session.flush()
                        row.state = "output_committed"
                        row.attempt_kind = "attempt_a"
                        row.output_committed_at = now
                        row.optimistic_version += 1
                        await session.flush()
                        attempt = Attempt(
                            owner_id=owner_id,
                            activity_instance_id=activity_id,
                            attempt_kind="attempt_a",
                            parent_attempt_id=None,
                            original_text=json.dumps(
                                {
                                    "task_context": {
                                        "exercise_type": exercise_type,
                                        "mapping_version": "seed-v1",
                                    },
                                    "output": {
                                        "draft_markdown": (
                                            "Webhooks deliver events; 200 means accepted."
                                        )
                                    },
                                }
                            ),
                            original_markdown="Webhooks deliver events; 200 means accepted.",
                            original_sql=None,
                            audience="engineer",
                            prompt="Explain webhook delivery.",
                            assistance_mode="none",
                            commitment_hash=b"h" * 32,
                            committed_at=now,
                            created_at=now,
                        )
                        session.add(attempt)
                        await session.flush()
                        row.state = "self_review_complete"
                        row.optimistic_version += 1
                        session.add(
                            SelfReview(
                                owner_id=owner_id,
                                activity_instance_id=activity_id,
                                attempt_id=attempt.id,
                                main_answer="Durable acceptance.",
                                did_well="Named the rule.",
                                structure_weakness="No close.",
                                vague_points="Retries.",
                                hesitation_points="None.",
                                change_next="Close with a decision.",
                                self_score=3,
                                submitted_at=now,
                            )
                        )

                transport = FakeTransport()
                reviewer = ReviewerService(transport, model="claude-fable-5-1")

                async with factory() as session:
                    before = await ReviewService(session, reviewer=reviewer).read(
                        owner_id=owner_id, activity_id=activity_id
                    )
                    assert before.status == "not_requested"

                processed = await review_step(factory, reviewer=reviewer)
                assert processed == 1
                assert len(transport.requests) == 1
                request = transport.requests[0]
                assert request.rubric_slug == "tam_block"  # type: ignore[attr-defined]
                assert "Learner's self-review" not in request.committed_attempt  # type: ignore[attr-defined]
                assert request.self_review and "Self-score: 3/4" in request.self_review  # type: ignore[attr-defined]

                async with factory() as session:
                    after = await ReviewService(session, reviewer=reviewer).read(
                        owner_id=owner_id, activity_id=activity_id
                    )
                    assert after.status == "ready", after
                    assert after.verdict == "Correct on delivery, silent on retries."
                    assert {d.slug for d in after.dimensions} == {
                        d.slug for d in bundle.rubric("tam_block").dimensions
                    }
                    assert after.dimensions[0].name and after.dimensions[0].maximum == 4
                    assert len(after.strengths) == 2 and len(after.corrections) == 2
                    assert after.evidence_status == "recorded", after.evidence_status
                    assert after.evidence_event_ids
                    review = await session.scalar(select(ActivityReview))
                    assert review is not None and review.model == "claude-fable-5-1"
                    activity = await session.get(ActivityInstance, activity_id)
                    assert activity is not None and activity.state == "feedback_ready"
                    status = await session.scalar(
                        select(ActivityProcessingStatus).where(
                            ActivityProcessingStatus.activity_instance_id == activity_id
                        )
                    )
                    assert status is not None and status.state == "ready"
                    events = await session.scalar(
                        select(func.count()).select_from(SkillEvidenceEvent)
                    )
                    assert events == len(after.evidence_event_ids) > 0
                    # The Progress read model sees the same review, the study day and the skills.
                    progress = await ProgressQueryService(session).read(owner_id=owner_id)
                    assert [a.activity_id for a in progress.assessments] == [activity_id]
                    assert progress.assessments[0].dimension_count == len(after.dimensions)
                    assert progress.assessments[0].average_score == Decimal("3.00")
                    assert len(progress.weeks) == 1 and progress.weeks[0].study_days == 1
                    moved = [s for s in progress.skills if s.latest_level is not None]
                    assert moved and all(s.points for s in moved)
                    assert progress.interviews == ()
                    notified = await session.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.event_type == "activity.feedback_ready")
                    )
                    assert notified == 1

                # The skill series shows the point and the event the review produced.
                async with factory() as session:
                    reader = SqlAlchemyEvidenceRepository(session)
                    first_event = await session.get(SkillEvidenceEvent, after.evidence_event_ids[0])
                    assert first_event is not None
                    competency = await session.get(Competency, first_event.competency_id)
                    assert competency is not None
                    series = await reader.skill_series(
                        owner_id=owner_id, skill_slug=competency.slug
                    )
                    assert series.final_target >= series.baseline
                    assert [e.event_id for e in series.events] == [first_event.id]
                    assert series.events[0].assistance == "ai_after_committed_attempt"
                    assert series.events[0].evaluator == "ai_rubric_reviewer"
                    assert len(series.points) == 1
                    assert series.points[0].snapshot_date == series.events[0].occurred_at.date()

                # A second pass finds nothing to do and never calls the reviewer again.
                assert await review_step(factory, reviewer=reviewer) == 0
                assert len(transport.requests) == 1
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
