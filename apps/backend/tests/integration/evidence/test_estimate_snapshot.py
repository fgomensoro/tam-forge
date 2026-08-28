from __future__ import annotations

import asyncio

import pytest
from _helpers import evaluation_command, seed_evidence_case

pytestmark = pytest.mark.integration


def test_snapshot_failure_rolls_back_the_complete_evidence_unit(
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

    class FailingSnapshotRepository(SqlAlchemyEvidenceRepository):
        async def _save_snapshot(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            raise RuntimeError("forced snapshot failure")

    async def exercise() -> None:
        case = await seed_evidence_case(test_database_url)
        try:
            async with case.session_factory() as session:
                with pytest.raises(RuntimeError, match="forced snapshot failure"):
                    await EvidenceService(FailingSnapshotRepository(session)).record(
                        owner_id=case.owner_id,
                        command=evaluation_command(case),
                        idempotency_key="portfolio-review-fails",
                    )
            async with case.session_factory() as session:
                for model in (
                    RubricEvaluation,
                    RubricDimensionScore,
                    SkillEvidenceEvent,
                    SkillSnapshot,
                    PortfolioJudgmentScore,
                    AuditEvent,
                    OutboxEvent,
                ):
                    assert await session.scalar(
                        select(func.count()).select_from(model)
                    ) == 0
                assert await session.scalar(
                    select(func.count()).select_from(CommandReceipt).where(
                        CommandReceipt.command_scope == "evidence.record"
                    )
                ) == 0
        finally:
            await case.engine.dispose()

    asyncio.run(exercise())


def test_snapshot_read_model_exposes_reproducible_lineage(
    test_database_url: str,
) -> None:
    from tamforge_backend.evidence.repository import SqlAlchemyEvidenceRepository
    from tamforge_backend.evidence.service import EvidenceService

    async def exercise() -> None:
        case = await seed_evidence_case(test_database_url)
        try:
            async with case.session_factory() as session:
                result = await EvidenceService(
                    SqlAlchemyEvidenceRepository(session)
                ).record(
                    owner_id=case.owner_id,
                    command=evaluation_command(case),
                    idempotency_key="portfolio-review-lineage",
                )
            async with case.session_factory() as session:
                reader = SqlAlchemyEvidenceRepository(session)
                skills = await reader.list_skills(owner_id=case.owner_id)
                scored = tuple(
                    item for item in skills.items if item.latest_snapshot is not None
                )
                assert len(scored) == 7
                for skill in scored:
                    snapshot = skill.latest_snapshot
                    assert snapshot is not None
                    assert snapshot.formula_version == "seed-v1"
                    assert snapshot.manifest
                    assert snapshot.confidence_basis["basis_code"] == "low_weight"
                    assert snapshot.trend_basis["basis_code"] == "too_few_events"
                    assert {
                        item.event_id for item in snapshot.manifest
                    }.issubset(set(result.evidence_event_ids))
                    assert snapshot.month_one_target_gap == (
                        skill.month_one_target - snapshot.estimated_level
                    )
        finally:
            await case.engine.dispose()

    asyncio.run(exercise())
