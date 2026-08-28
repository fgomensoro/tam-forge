from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from _helpers import evaluation_command, seed_evidence_case

pytestmark = pytest.mark.integration


def test_evidence_ledger_is_atomic_idempotent_and_owner_scoped(
    test_database_url: str,
) -> None:
    from sqlalchemy import func, select
    from tamforge_backend.auth.models import AuditEvent, CommandReceipt
    from tamforge_backend.evidence.models import (
        PortfolioJudgmentScore,
        RubricDimensionScore,
        RubricEvaluation,
        SkillEvidenceEvent,
        SkillSnapshot,
    )
    from tamforge_backend.evidence.repository import SqlAlchemyEvidenceRepository
    from tamforge_backend.evidence.service import EvidenceService
    from tamforge_backend.notifications.models import OutboxEvent

    async def exercise() -> None:
        case = await seed_evidence_case(test_database_url)
        command = evaluation_command(case)
        try:
            async with case.session_factory() as session:
                service = EvidenceService(SqlAlchemyEvidenceRepository(session))
                first = await service.record(
                    owner_id=case.owner_id,
                    command=command,
                    idempotency_key="portfolio-review-1",
                )
            async with case.session_factory() as session:
                replayed = await EvidenceService(
                    SqlAlchemyEvidenceRepository(session)
                ).record(
                    owner_id=case.owner_id,
                    command=command,
                    idempotency_key="portfolio-review-1",
                )
                assert replayed == first
                assert len(first.evidence_event_ids) == 7
                assert len(first.snapshot_ids) == 7
                assert first.portfolio_score_id is not None
                assert await session.scalar(
                    select(func.count()).select_from(RubricEvaluation)
                ) == 1
                assert await session.scalar(
                    select(func.count()).select_from(RubricDimensionScore)
                ) == 7
                assert await session.scalar(
                    select(func.count()).select_from(SkillEvidenceEvent)
                ) == 7
                assert await session.scalar(
                    select(func.count()).select_from(SkillSnapshot)
                ) == 7
                assert await session.scalar(
                    select(func.count()).select_from(PortfolioJudgmentScore)
                ) == 1
                assert await session.scalar(
                    select(func.count()).select_from(AuditEvent)
                ) == 1
                assert await session.scalar(
                    select(func.count()).select_from(OutboxEvent)
                ) == 1
                assert await session.scalar(
                    select(func.count()).select_from(CommandReceipt).where(
                        CommandReceipt.command_scope == "evidence.record"
                    )
                ) == 1
        finally:
            await case.engine.dispose()

    asyncio.run(exercise())


def test_early_portfolio_history_is_stored_as_insufficient(
    test_database_url: str,
) -> None:
    from sqlalchemy import select
    from tamforge_backend.database import transaction_scope
    from tamforge_backend.evidence.models import (
        PortfolioJudgmentScore,
        RubricEvaluation,
    )
    from tamforge_backend.evidence.repository import SqlAlchemyEvidenceRepository
    from tamforge_backend.evidence.service import EvidenceService

    async def exercise() -> None:
        case = await seed_evidence_case(test_database_url)
        try:
            async with case.session_factory() as session:
                await EvidenceService(SqlAlchemyEvidenceRepository(session)).record(
                    owner_id=case.owner_id,
                    command=evaluation_command(case),
                    idempotency_key="portfolio-review-first",
                )
            async with case.session_factory() as session:
                async with transaction_scope(session):
                    first = (
                        await session.scalars(
                            select(PortfolioJudgmentScore).where(
                                PortfolioJudgmentScore.owner_id == case.owner_id
                            )
                        )
                    ).one()
                    first_evaluation = await session.get(
                        RubricEvaluation,
                        first.rubric_evaluation_id,
                    )
                    assert first_evaluation is not None
                    now = datetime.now(UTC)
                    second_evaluation = RubricEvaluation(
                        owner_id=first_evaluation.owner_id,
                        config_seed_version_id=(
                            first_evaluation.config_seed_version_id
                        ),
                        activity_instance_id=first_evaluation.activity_instance_id,
                        attempt_id=first_evaluation.attempt_id,
                        rubric_version_id=first_evaluation.rubric_version_id,
                        evaluator_kind="human_coach",
                        evaluation_schema_version=(
                            first_evaluation.evaluation_schema_version
                        ),
                        input_manifest=first_evaluation.input_manifest,
                        evaluated_at=now,
                        created_at=now,
                    )
                    session.add(second_evaluation)
                    await session.flush()
                    second = PortfolioJudgmentScore(
                        owner_id=first.owner_id,
                        config_seed_version_id=first.config_seed_version_id,
                        activity_instance_id=first.activity_instance_id,
                        attempt_id=first.attempt_id,
                        rubric_evaluation_id=second_evaluation.id,
                        rubric_version_id=first.rubric_version_id,
                        formula_version=first.formula_version,
                        impact_risk_assessment=first.impact_risk_assessment,
                        explicit_prioritization=first.explicit_prioritization,
                        delegation_ownership=first.delegation_ownership,
                        communication_control=first.communication_control,
                        proactive_work_protection=first.proactive_work_protection,
                        evidence_based_reprioritization=(
                            first.evidence_based_reprioritization
                        ),
                        english_clarity=first.english_clarity,
                        total_score=first.total_score,
                        trend_basis={
                            "schema_version": 1,
                            "basis_code": "too_few_events",
                            "event_ids": [first.id],
                        },
                        scored_at=now,
                        created_at=now,
                    )
                    session.add(second)
                    await session.flush()
                    assert second.trend_basis["basis_code"] == "too_few_events"
        finally:
            await case.engine.dispose()

    asyncio.run(exercise())
