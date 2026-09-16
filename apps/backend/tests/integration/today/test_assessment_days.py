"""A Saturday's contract is scored by the reviewer; the day reads back with its result."""

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
    async def review(self, request: object) -> Mapping[str, object]:
        dims = request.dimensions  # type: ignore[attr-defined]
        return {
            "verdict": "Correct joins, one missed filter.",
            "dimensions": [
                {"slug": d.slug, "score": "3", "rationale": "Shown.", "evidence": "JOIN"}
                for d in dims
            ],
            "strengths": [{"statement": "Right grain."}, {"statement": "Named the key."}],
            "corrections": [
                {"statement": "Filter nulls.", "instruction": "Add the WHERE clause."},
                {"statement": "Explain the total.", "instruction": "State what it means."},
            ],
            "next_practice": "Repeat task 6 in twenty minutes.",
        }


@pytest.mark.integration
def test_assessment_day_records_each_contract_with_a_score(test_database_url: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tamforge_backend.agents.roles.reviewer import ReviewerService
    from tamforge_backend.assessments.service import AssessmentQueryService
    from tamforge_backend.database import database_url_to_sync, transaction_scope
    from tamforge_backend.evidence.config_loader import load_config_bundle
    from tamforge_backend.evidence.models import SkillEvidenceEvent
    from tamforge_backend.evidence.seed import seed_config
    from tamforge_backend.learning.models import ActivityInstance, Attempt, SelfReview
    from tamforge_backend.learning.repository import StudyDayService
    from tamforge_backend.progress.service import ProgressQueryService
    from tamforge_backend.roadmaps.models import TaskDefinition
    from tamforge_backend.roadmaps.package import inspect_zip_stream
    from tamforge_backend.roadmaps.repository import SqlAlchemyRoadmapRepository
    from tamforge_backend.roadmaps.service import RoadmapService
    from tamforge_backend.storage.fake import InMemoryObjectStore
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
                            idempotency_key="assessment-roadmap",
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
                    # Saturday 2026-08-29 is day 6 of the scheme: the assessment day.
                    day = await StudyDayService(session).ensure_current_day(
                        owner_id=owner_id, at=datetime(2026, 8, 29, 19, tzinfo=UTC)
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
                    assert rows and all(d.block == "saturday_assessment" for _, d in rows)
                    activity, definition = next(
                        (a, d) for a, d in rows if d.exercise_type == "sql_no_ai_timed_assessment"
                    )
                    activity_id, contract_count = activity.id, len(rows)
                    await session.rollback()

                async with factory() as session:
                    before = await AssessmentQueryService(session).list(owner_id=owner_id)
                    assert len(before.items) == 1
                    assert before.items[0].local_date.isoformat() == "2026-08-29"
                    assert len(before.items[0].contracts) == contract_count
                    assert {c.result for c in before.items[0].contracts} == {"not_attempted"}
                    assert before.items[0].average_score is None
                    sql_contract = next(
                        c for c in before.items[0].contracts if c.activity_id == activity_id
                    )
                    assert sql_contract.contract_type == "saturday_sql"

                async with factory() as session:
                    async with transaction_scope(session):
                        row = await session.get(ActivityInstance, activity_id)
                        assert row is not None
                        now = datetime.now(UTC)
                        row.state = "active"
                        row.started_at = now
                        row.optimistic_version += 1
                        await session.flush()
                        # Assessment activities are born as no-AI assessments; the kind stays.
                        row.state = "output_committed"
                        row.output_committed_at = now
                        row.optimistic_version += 1
                        await session.flush()
                        attempt = Attempt(
                            owner_id=owner_id,
                            activity_instance_id=activity_id,
                            attempt_kind="no_ai_assessment",
                            parent_attempt_id=None,
                            original_text=json.dumps(
                                {
                                    "task_context": {
                                        "exercise_type": "sql_no_ai_timed_assessment",
                                        "mapping_version": "seed-v1",
                                    },
                                    "output": {"sql": "SELECT 1"},
                                }
                            ),
                            original_markdown=None,
                            original_sql="SELECT account_id, SUM(amount) FROM ledger GROUP BY 1",
                            audience="engineer",
                            prompt="Northstar tasks 5 to 8.",
                            assistance_mode="none",
                            commitment_hash=b"s" * 32,
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
                                main_answer="Per-account totals.",
                                did_well="Grouped correctly.",
                                structure_weakness="No null filter.",
                                vague_points="None.",
                                hesitation_points="Window functions.",
                                change_next="Filter first.",
                                self_score=3,
                                submitted_at=now,
                            )
                        )

                reviewer = ReviewerService(FakeTransport(), model="claude-fable-5-1")
                assert await review_step(factory, reviewer=reviewer) == 1

                async with factory() as session:
                    after = await AssessmentQueryService(session).list(owner_id=owner_id)
                    day_result = after.items[0]
                    scored = next(c for c in day_result.contracts if c.activity_id == activity_id)
                    assert scored.result == "scored"
                    assert scored.average_score == Decimal("3.00")
                    assert scored.dimension_count == len(bundle.rubric("tam_block").dimensions)
                    assert scored.review_id is not None and scored.evidence_event_ids
                    assert day_result.scored_contracts == 1
                    assert day_result.average_score == Decimal("3.00")
                    # The score fed the skill series as timed-assessment evidence.
                    events = (
                        await session.scalars(
                            select(SkillEvidenceEvent).where(
                                SkillEvidenceEvent.id.in_(scored.evidence_event_ids)
                            )
                        )
                    ).all()
                    assert events and all(e.practice_mode == "timed_assessment" for e in events)
                    await session.rollback()
                    progress = await ProgressQueryService(session).read(owner_id=owner_id)
                    assert [d.local_date for d in progress.assessment_days] == [
                        day_result.local_date
                    ]
                    assert progress.assessments[0].block == "saturday_assessment"
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
