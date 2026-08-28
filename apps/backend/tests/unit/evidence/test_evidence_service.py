"""Evidence orchestration and immutable-lineage tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from tamforge_backend.evidence.config_loader import load_config_bundle
from tamforge_backend.evidence.schemas import (
    DimensionEvaluationInput,
    EvidenceEvaluationCommand,
    RecordEvaluationResponse,
    SkillDimensionSubsetInput,
)
from tamforge_backend.evidence.service import (
    EvaluationContext,
    EvidenceConflict,
    EvidenceService,
    PersistedDimension,
    PersistedSkill,
)

CONFIG_DIR = Path(__file__).parents[5] / "config"
NOW = datetime(2026, 8, 28, 12, tzinfo=UTC)


def _dimensions() -> tuple[DimensionEvaluationInput, ...]:
    return (
        DimensionEvaluationInput(
            dimension_slug="impact_risk_assessment",
            availability="scored",
            score=Decimal("4"),
        ),
        DimensionEvaluationInput(
            dimension_slug="explicit_prioritization",
            availability="scored",
            score=Decimal("3"),
        ),
        DimensionEvaluationInput(
            dimension_slug="delegation_ownership",
            availability="scored",
            score=Decimal("2"),
        ),
        DimensionEvaluationInput(
            dimension_slug="communication_control",
            availability="scored",
            score=Decimal("3"),
        ),
        DimensionEvaluationInput(
            dimension_slug="proactive_work_protection",
            availability="scored",
            score=Decimal("2"),
        ),
        DimensionEvaluationInput(
            dimension_slug="evidence_based_reprioritization",
            availability="scored",
            score=Decimal("3"),
        ),
        DimensionEvaluationInput(
            dimension_slug="english_clarity",
            availability="scored",
            score=Decimal("2"),
        ),
    )


def _skill_subsets(slugs: tuple[str, ...]) -> tuple[SkillDimensionSubsetInput, ...]:
    dimension_slugs = tuple(item.dimension_slug for item in _dimensions())
    assert len(slugs) <= len(dimension_slugs)
    return tuple(
        SkillDimensionSubsetInput(
            skill_slug=skill_slug,
            dimension_slugs=(dimension_slugs[index],),
        )
        for index, skill_slug in enumerate(slugs)
    )


def _context(
    exercise_slug: str,
    *,
    selected_competency: str | None = None,
    self_score: int = 0,
    attempt_kind: str = "attempt_a",
    attempt_assistance_mode: str = "none",
) -> EvaluationContext:
    bundle = load_config_bundle(CONFIG_DIR)
    rubric = bundle.portfolio
    return EvaluationContext(
        config_seed_version_id=1,
        config_version_key=bundle.version_key,
        formula=bundle.formula,
        exercise=bundle.exercise(exercise_slug),
        exercise_type_version_id=10,
        rubric=rubric,
        rubric_version_id=20,
        dimensions=tuple(
            PersistedDimension(
                id=index,
                slug=item.slug,
                weight=item.weight,
                maximum=item.maximum,
            )
            for index, item in enumerate(rubric.dimensions, start=1)
        ),
        skills={
            item.slug: PersistedSkill(
                id=index,
                slug=item.slug,
                baseline=item.baseline,
                month_one_target=item.month_one_target,
                final_target=item.final_target,
            )
            for index, item in enumerate(bundle.skills, start=1)
        },
        activity_id=30,
        attempt_id=40,
        attempt_kind=attempt_kind,
        attempt_assistance_mode=attempt_assistance_mode,
        attempt_committed_at=NOW - timedelta(minutes=10),
        self_review_submitted_at=NOW - timedelta(minutes=5),
        prompt="Prioritize the customer portfolio and defend the decision.",
        selected_competency=selected_competency,
        selector_field=(
            "domain_competency_slug" if selected_competency is not None else None
        ),
        selector_committed_in_attempt=selected_competency is not None,
        self_score=self_score,
        linked_artifact_classes={101: "transcript", 102: "original_audio"},
    )


def _command(
    context: EvaluationContext,
    *,
    english_available: bool,
    skill_slugs: tuple[str, ...],
    assistance: str = "ai_after_committed_attempt",
    formula_version: str = "seed-v1",
) -> EvidenceEvaluationCommand:
    dimensions = _dimensions()
    if english_available:
        dimensions = (
            dimensions[0].model_copy(
                update={"evidence_artifact_ids": (101, 102)}
            ),
            *dimensions[1:],
        )
    return EvidenceEvaluationCommand(
        activity_id=context.activity_id,
        attempt_id=context.attempt_id,
        config_version_key=context.config_version_key,
        exercise_type=context.exercise.slug,
        mapping_version=context.exercise.mapping_version,
        formula_version=formula_version,
        rubric_slug=context.rubric.slug,
        rubric_version=context.rubric.version,
        practice_mode=context.exercise.evidence_mode,
        assistance=assistance,
        evaluator="ai_rubric_reviewer",
        difficulty="standard",
        ai_role="reviewer",
        evaluated_at=NOW,
        artifact_ids=(101, 102) if english_available else (),
        observation_ids=(),
        transcript_available=english_available,
        audio_available=english_available,
        written_english_available=False,
        scored_recording=english_available,
        dimensions=dimensions,
        skill_dimension_subsets=_skill_subsets(skill_slugs),
    )


def test_self_score_is_never_substituted_and_each_skill_uses_its_own_subset() -> None:
    context = _context("portfolio_triage", self_score=0)
    skills = tuple(item.skill_slug for item in context.exercise.impacts)
    prepared = EvidenceService.prepare_evaluation(
        context=context,
        command=_command(context, english_available=True, skill_slugs=skills),
    )

    assert prepared.self_score == 0
    assert len(prepared.skill_events) == len(skills)
    assert {item.skill_slug for item in prepared.skill_events} == set(skills)
    assert all(len(item.dimension_slugs) == 1 for item in prepared.skill_events)
    assert len({item.dimension_slugs for item in prepared.skill_events}) == len(skills)
    assert {item.performance_score for item in prepared.skill_events} != {Decimal("0")}
    assert prepared.portfolio_components is not None


def test_conditional_tam_english_exists_only_with_english_evidence() -> None:
    context = _context("troubleshooting_case")
    without_english = tuple(
        item.skill_slug
        for item in context.exercise.impacts
        if item.skill_slug != "tam_english"
    )
    prepared = EvidenceService.prepare_evaluation(
        context=context,
        command=_command(
            context,
            english_available=False,
            skill_slugs=without_english,
        ),
    )
    assert "tam_english" not in {item.skill_slug for item in prepared.skill_events}

    with pytest.raises(EvidenceConflict, match="mapped skills"):
        EvidenceService.prepare_evaluation(
            context=context,
            command=_command(
                context,
                english_available=False,
                skill_slugs=without_english + ("tam_english",),
            ),
        )


def test_dynamic_impact_comes_only_from_allowlisted_committed_attempt_field() -> None:
    missing = _context("audience_switching_explanation")
    static = tuple(item.skill_slug for item in missing.exercise.impacts)
    with pytest.raises(EvidenceConflict, match="precommit selector"):
        EvidenceService.prepare_evaluation(
            context=missing,
            command=_command(missing, english_available=True, skill_slugs=static),
        )

    selected = _context(
        "audience_switching_explanation",
        selected_competency="sql_reconciliation",
    )
    prepared = EvidenceService.prepare_evaluation(
        context=selected,
        command=_command(
            selected,
            english_available=True,
            skill_slugs=static + ("sql_reconciliation",),
        ),
    )
    dynamic = next(
        item for item in prepared.skill_events if item.skill_slug == "sql_reconciliation"
    )
    assert dynamic.skill_impact == Decimal("0.30")
    assert dynamic.impact_source == "precommit_selector"


def test_mismatched_immutable_versions_fail_closed() -> None:
    context = _context("troubleshooting_case")
    skills = tuple(
        item.skill_slug
        for item in context.exercise.impacts
        if item.skill_slug != "tam_english"
    )
    with pytest.raises(EvidenceConflict, match="formula version"):
        EvidenceService.prepare_evaluation(
            context=context,
            command=_command(
                context,
                english_available=False,
                skill_slugs=skills,
                formula_version="other-v1",
            ),
        )


def test_nonqualifying_evidence_remains_visible_but_cannot_raise_level() -> None:
    context = _context(
        "troubleshooting_case", attempt_assistance_mode="hint_ladder"
    )
    skills = tuple(
        item.skill_slug
        for item in context.exercise.impacts
        if item.skill_slug != "tam_english"
    )
    prepared = EvidenceService.prepare_evaluation(
        context=context,
        command=_command(
            context,
            english_available=False,
            skill_slugs=skills,
            assistance="ai_hints_during_attempt",
        ),
    )
    assert prepared.skill_events
    assert all(not item.qualifying_for_level for item in prepared.skill_events)
    assert {item.qualification_reason for item in prepared.skill_events} == {
        "assisted_during_attempt"
    }


def test_attempt_b_is_comparison_only_and_creates_no_progress_evidence() -> None:
    context = _context("portfolio_triage", attempt_kind="attempt_b")
    prepared = EvidenceService.prepare_evaluation(
        context=context,
        command=_command(
            context,
            english_available=True,
            skill_slugs=(),
        ),
    )

    assert prepared.skill_events == ()
    assert prepared.portfolio_components is None


class _FakeStore:
    def __init__(self, context: EvaluationContext) -> None:
        self.context = context
        self.saved: dict[str, tuple[bytes, RecordEvaluationResponse]] = {}
        self.write_count = 0

    async def record_atomic(  # type: ignore[no-untyped-def]
        self,
        *,
        owner_id,
        idempotency_key,
        request_hash,
        command,
        prepare,
    ):
        del owner_id, command
        duplicate = self.saved.get(idempotency_key)
        if duplicate is not None:
            if duplicate[0] != request_hash:
                raise EvidenceConflict("Idempotency-Key was reused")
            return duplicate[1]
        prepared = prepare(self.context)
        self.write_count += 1
        result = RecordEvaluationResponse(
            evaluation_id=50,
            activity_id=prepared.activity_id,
            attempt_id=prepared.attempt_id,
            evidence_event_ids=(61, 62),
            snapshot_ids=(71, 72),
            portfolio_score_id=80,
            replayed=False,
        )
        self.saved[idempotency_key] = (request_hash, result)
        return result


@pytest.mark.anyio
async def test_duplicate_idempotency_key_returns_original_without_second_write() -> None:
    context = _context("portfolio_triage")
    skills = tuple(item.skill_slug for item in context.exercise.impacts)
    command = _command(context, english_available=True, skill_slugs=skills)
    store = _FakeStore(context)
    service = EvidenceService(store)

    first = await service.record(
        owner_id=1,
        command=command,
        idempotency_key="reviewer-run-1",
    )
    second = await service.record(
        owner_id=1,
        command=command,
        idempotency_key="reviewer-run-1",
    )

    assert second == first
    assert store.write_count == 1
