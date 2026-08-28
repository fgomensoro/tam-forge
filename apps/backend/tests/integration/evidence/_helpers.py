from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tamforge_backend.database import database_url_to_sync, transaction_scope
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.schemas import (
    DimensionEvaluationInput,
    EvidenceEvaluationCommand,
    SkillDimensionSubsetInput,
)
from tamforge_backend.evidence.seed import seed_config

ROOT = Path(__file__).parents[5]


@dataclass(frozen=True, slots=True)
class SeededEvidenceCase:
    owner_id: int
    activity_id: int
    attempt_id: int
    config_version_key: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


async def seed_evidence_case(test_database_url: str) -> SeededEvidenceCase:
    alembic = Config("apps/backend/alembic.ini")
    alembic.attributes["database_url"] = test_database_url
    command.downgrade(alembic, "base")
    command.upgrade(alembic, "head")
    sync_engine = create_engine(database_url_to_sync(test_database_url))
    bundle = load_config_bundle(ROOT / "config")
    try:
        with sync_engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO owners (github_user_id, github_login) "
                    "VALUES (102269369, 'fgomensoro') RETURNING id"
                )
            ).scalar_one()
            source_id = connection.execute(
                text(
                    "INSERT INTO roadmap_sources "
                    "(owner_id, source_key, name, source_kind) VALUES "
                    "(:owner, 'evidence-test', 'Evidence test roadmap', 'obsidian') "
                    "RETURNING id"
                ),
                {"owner": owner_id},
            ).scalar_one()
            version_id = connection.execute(
                text(
                    "INSERT INTO roadmap_versions "
                    "(owner_id, source_id, version_key, version_number, month_number, "
                    "content_hash, object_key, manifest, raw_payload, normalized_payload, "
                    "mirror_status, state) VALUES "
                    "(:owner, :source, 'month-1-evidence-test', 1, 1, :hash, "
                    "'owners/test/roadmaps/evidence.json', '{}'::jsonb, '{}'::jsonb, "
                    "'{}'::jsonb, 'not_required', 'draft') RETURNING id"
                ),
                {"owner": owner_id, "source": source_id, "hash": b"r" * 32},
            ).scalar_one()
            node_id = connection.execute(
                text(
                    "INSERT INTO curriculum_nodes "
                    "(owner_id, roadmap_version_id, stable_id, ordinal, kind, title) "
                    "VALUES (:owner, :version, 'week-portfolio', 1, 'week', "
                    "'Portfolio') RETURNING id"
                ),
                {"owner": owner_id, "version": version_id},
            ).scalar_one()
            task_id = connection.execute(
                text(
                    "INSERT INTO task_definitions "
                    "(owner_id, roadmap_version_id, curriculum_node_id, stable_id, "
                    "exercise_type, mapping_version, objective, timebox_minutes, block, "
                    "required, output_contract, pass_contract, evidence_contract, "
                    "source_references, allowed_ai_role) VALUES "
                    "(:owner, :version, :node, 'portfolio-case-1', 'portfolio_triage', "
                    "'seed-v1', 'Prioritize the portfolio', 60, 'tam_case', true, "
                    "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, 'interviewer') "
                    "RETURNING id"
                ),
                {"owner": owner_id, "version": version_id, "node": node_id},
            ).scalar_one()
            day_id = connection.execute(
                text(
                    "INSERT INTO study_days "
                    "(owner_id, roadmap_version_id, local_date, planned_minutes, "
                    "focused_minutes, day_type, status) VALUES "
                    "(:owner, :version, CURRENT_DATE, 240, 0, 'weekday', 'planned') "
                    "RETURNING id"
                ),
                {"owner": owner_id, "version": version_id},
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE study_days SET status = 'in_progress', started_at = now() "
                    "WHERE owner_id = :owner AND id = :day"
                ),
                {"owner": owner_id, "day": day_id},
            )
            activity_id = connection.execute(
                text(
                    "INSERT INTO activity_instances "
                    "(owner_id, study_day_id, roadmap_version_id, task_definition_id, "
                    "task_stable_id_snapshot, task_mapping_version_snapshot, "
                    "task_objective_snapshot, task_timebox_minutes_snapshot, "
                    "roadmap_version_key_snapshot, state, attempt_kind, assistance_mode, "
                    "classification, timebox_minutes, source_hidden, optimistic_version, "
                    "replacement_version) VALUES "
                    "(:owner, :day, :version, :task, 'portfolio-case-1', 'seed-v1', "
                    "'Prioritize the portfolio', 60, 'month-1-evidence-test', 'ready', "
                    "'attempt_a', 'none', 'required', 60, false, 1, 1) RETURNING id"
                ),
                {
                    "owner": owner_id,
                    "day": day_id,
                    "version": version_id,
                    "task": task_id,
                },
            ).scalar_one()
            connection.execute(
                text(
                    "UPDATE activity_instances SET state = 'active', started_at = now(), "
                    "optimistic_version = 2 WHERE owner_id = :owner AND id = :activity"
                ),
                {"owner": owner_id, "activity": activity_id},
            )
            connection.execute(
                text(
                    "UPDATE activity_instances SET state = 'output_committed', "
                    "output_committed_at = now(), optimistic_version = 3 "
                    "WHERE owner_id = :owner AND id = :activity"
                ),
                {"owner": owner_id, "activity": activity_id},
            )
            canonical = json.dumps(
                {
                    "contract_version": 1,
                    "task_context": {
                        "exercise_type": "portfolio_triage",
                        "mapping_version": "seed-v1",
                    },
                    "output": {"kind": "case"},
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            attempt_id = connection.execute(
                text(
                    "INSERT INTO attempts "
                    "(owner_id, activity_instance_id, attempt_kind, original_text, "
                    "original_markdown, audience, prompt, assistance_mode, commitment_hash, "
                    "committed_at) VALUES (:owner, :activity, 'attempt_a', :text, "
                    "'Portfolio recommendation', 'Hiring manager', "
                    "'Prioritize the customer portfolio and defend the decision.', 'none', "
                    ":hash, now()) RETURNING id"
                ),
                {
                    "owner": owner_id,
                    "activity": activity_id,
                    "text": canonical,
                    "hash": b"a" * 32,
                },
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO self_reviews "
                    "(owner_id, activity_instance_id, attempt_id, main_answer, did_well, "
                    "structure_weakness, vague_points, hesitation_points, change_next, "
                    "self_score) VALUES (:owner, :activity, :attempt, 'Priority order', "
                    "'Clear impact', 'Delegation', 'One assumption', 'One pause', "
                    "'State capacity', 0)"
                ),
                {"owner": owner_id, "activity": activity_id, "attempt": attempt_id},
            )
            connection.execute(
                text(
                    "UPDATE activity_instances SET state = 'self_review_complete', "
                    "optimistic_version = 4 WHERE owner_id = :owner AND id = :activity"
                ),
                {"owner": owner_id, "activity": activity_id},
            )

        async_url = make_url(test_database_url).set(drivername="postgresql+asyncpg")
        engine = create_async_engine(async_url)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with factory() as session:
            async with transaction_scope(session):
                await seed_config(
                    bundle,
                    owner_id=owner_id,
                    session=session,
                    apply=True,
                )
        return SeededEvidenceCase(
            owner_id=owner_id,
            activity_id=activity_id,
            attempt_id=attempt_id,
            config_version_key=bundle.version_key,
            engine=engine,
            session_factory=factory,
        )
    finally:
        sync_engine.dispose()


def evaluation_command(case: SeededEvidenceCase) -> EvidenceEvaluationCommand:
    now = datetime.now(UTC)
    dimensions = (
        ("impact_risk_assessment", "4"),
        ("explicit_prioritization", "3"),
        ("delegation_ownership", "2"),
        ("communication_control", "3"),
        ("proactive_work_protection", "2"),
        ("evidence_based_reprioritization", "3"),
        ("english_clarity", "2"),
    )
    skills = (
        "proactive_account_strategy",
        "cross_functional_influence",
        "incident_escalation_management",
        "business_value_framing",
        "executive_communication",
        "tam_english",
        "structured_troubleshooting",
    )
    return EvidenceEvaluationCommand(
        activity_id=case.activity_id,
        attempt_id=case.attempt_id,
        config_version_key=case.config_version_key,
        exercise_type="portfolio_triage",
        mapping_version="seed-v1",
        formula_version="seed-v1",
        rubric_slug="portfolio_judgment",
        rubric_version="seed-v1",
        practice_mode="mock_interview",
        assistance="ai_after_committed_attempt",
        evaluator="ai_rubric_reviewer",
        difficulty="standard",
        ai_role="reviewer",
        evaluated_at=now,
        artifact_ids=(),
        observation_ids=(),
        transcript_available=False,
        audio_available=False,
        written_english_available=True,
        scored_recording=False,
        dimensions=tuple(
            DimensionEvaluationInput(
                dimension_slug=slug,
                availability="scored",
                score=score,
            )
            for slug, score in dimensions
        ),
        skill_dimension_subsets=tuple(
            SkillDimensionSubsetInput(
                skill_slug=skill,
                dimension_slugs=(dimensions[index][0],),
            )
            for index, skill in enumerate(skills)
        ),
    )
