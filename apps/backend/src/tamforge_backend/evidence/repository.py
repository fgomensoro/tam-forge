"""PostgreSQL persistence and stable read models for evidence history."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.audit import (
    AuditCountKey,
    AuditFlagKey,
    AuditMetadataV1,
    AuditOutcome,
    AuditReasonCode,
)
from ..auth.models import AuditEvent, CommandReceipt, Owner
from ..database import transaction_scope
from ..learning.models import (
    ActivityArtifactLink,
    ActivityInstance,
    Artifact,
    Attempt,
    SelfReview,
)
from ..models.base import utc_now
from ..notifications.models import OutboxEvent
from .confidence import SkillEvidence, estimate_skill
from .config_loader import ConfigError, load_config_payload
from .models import (
    Competency,
    ConfigSeedVersion,
    ExerciseTypeVersion,
    PortfolioJudgmentScore,
    RubricDimension,
    RubricDimensionScore,
    RubricEvaluation,
    RubricVersion,
    SkillEvidenceEvent,
    SkillSnapshot,
)
from .portfolio import PortfolioHistoryItem, score_portfolio_judgment
from .schemas import (
    EvidenceEvaluationCommand,
    EvidenceEventPage,
    EvidenceEventResponse,
    PortfolioComponentResponse,
    PortfolioHistoryResponse,
    PortfolioScoreResponse,
    RecordEvaluationResponse,
    SkillListResponse,
    SkillSnapshotResponse,
    SkillSummaryResponse,
    SnapshotManifestItem,
)
from .service import (
    EvaluationContext,
    EvidenceConflict,
    EvidenceInvalidRequest,
    EvidenceNotFound,
    PersistedDimension,
    PersistedSkill,
    PreparedEvaluation,
)

_SCORE_QUANTUM = Decimal("0.001")
_SNAPSHOT_MANIFEST_LIMIT = 24
_READ_LIMIT_MAX = 100


def _json_number(value: Decimal) -> int | float:
    integral = value.to_integral_value()
    if value == integral:
        return int(integral)
    return float(value)


class SqlAlchemyEvidenceRepository:
    """Append evidence and materialized estimates under one owner lock."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._clock = clock

    async def record_atomic(
        self,
        *,
        owner_id: int,
        idempotency_key: str,
        request_hash: bytes,
        command: EvidenceEvaluationCommand,
        prepare: Callable[[EvaluationContext], PreparedEvaluation],
    ) -> RecordEvaluationResponse:
        async with transaction_scope(self._session):
            await self._lock_owner(owner_id)
            duplicate = await self._duplicate(
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if duplicate is not None:
                return duplicate
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise EvidenceInvalidRequest("repository clock must be timezone-aware")
            if command.evaluated_at > now:
                raise EvidenceConflict("evaluation timestamp cannot be in the future")
            context = await self._load_context(owner_id=owner_id, command=command)
            prepared = prepare(context)
            evaluation = await self._save_evaluation(
                owner_id=owner_id,
                prepared=prepared,
                now=now,
            )
            dimension_rows = await self._save_dimension_scores(
                owner_id=owner_id,
                evaluation=evaluation,
                prepared=prepared,
                now=now,
            )
            events = await self._save_skill_events(
                owner_id=owner_id,
                evaluation=evaluation,
                dimension_rows=dimension_rows,
                prepared=prepared,
                now=now,
            )
            snapshot_ids: list[int] = []
            for skill_id in sorted({item.competency_id for item in events}):
                snapshot = await self._save_snapshot(
                    owner_id=owner_id,
                    skill_id=skill_id,
                    prepared=prepared,
                    now=now,
                )
                snapshot_ids.append(snapshot.id)
            portfolio = await self._save_portfolio_score(
                owner_id=owner_id,
                evaluation=evaluation,
                prepared=prepared,
                now=now,
            )
            await self._save_audit_and_outbox(
                owner_id=owner_id,
                evaluation_id=evaluation.id,
                activity_id=prepared.activity_id,
                event_count=len(events),
                idempotency_key=idempotency_key,
                now=now,
            )
            result = RecordEvaluationResponse(
                evaluation_id=evaluation.id,
                activity_id=prepared.activity_id,
                attempt_id=prepared.attempt_id,
                evidence_event_ids=tuple(item.id for item in events),
                snapshot_ids=tuple(snapshot_ids),
                portfolio_score_id=portfolio.id if portfolio is not None else None,
                replayed=False,
            )
            self._session.add(
                CommandReceipt(
                    owner_id=owner_id,
                    command_scope="evidence.record",
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    status="completed",
                    result_payload=result.model_dump(mode="json"),
                    created_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
            await self._session.flush()
            return result

    async def _lock_owner(self, owner_id: int) -> None:
        locked = await self._session.scalar(
            select(Owner.id).where(Owner.id == owner_id).with_for_update()
        )
        if locked is None:
            raise EvidenceNotFound("evidence owner was not found")

    async def _duplicate(
        self, *, owner_id: int, idempotency_key: str, request_hash: bytes
    ) -> RecordEvaluationResponse | None:
        receipt = await self._session.scalar(
            select(CommandReceipt)
            .where(CommandReceipt.owner_id == owner_id)
            .where(CommandReceipt.command_scope == "evidence.record")
            .where(CommandReceipt.idempotency_key == idempotency_key)
            .with_for_update()
        )
        if receipt is None:
            return None
        if receipt.request_hash != request_hash:
            raise EvidenceConflict("Idempotency-Key was reused for another evaluation")
        return RecordEvaluationResponse.model_validate(receipt.result_payload)

    async def _load_context(
        self, *, owner_id: int, command: EvidenceEvaluationCommand
    ) -> EvaluationContext:
        config = await self._session.scalar(
            select(ConfigSeedVersion)
            .where(ConfigSeedVersion.owner_id == owner_id)
            .where(ConfigSeedVersion.version_key == command.config_version_key)
            .with_for_update(read=True, key_share=True)
        )
        if config is None:
            raise EvidenceNotFound("configuration version was not found")
        try:
            bundle = load_config_payload(config.canonical_payload)
            exercise_config = bundle.exercise(command.exercise_type)
            rubric_config = bundle.rubric(command.rubric_slug)
        except (ConfigError, KeyError) as exc:
            raise EvidenceConflict("persisted evidence configuration is invalid") from exc

        attempt_row = (
            await self._session.execute(
                select(ActivityInstance, Attempt, SelfReview)
                .join(
                    Attempt,
                    (Attempt.owner_id == ActivityInstance.owner_id)
                    & (Attempt.activity_instance_id == ActivityInstance.id),
                )
                .join(
                    SelfReview,
                    (SelfReview.owner_id == Attempt.owner_id)
                    & (SelfReview.activity_instance_id == Attempt.activity_instance_id)
                    & (SelfReview.attempt_id == Attempt.id),
                )
                .where(ActivityInstance.owner_id == owner_id)
                .where(ActivityInstance.id == command.activity_id)
                .where(Attempt.id == command.attempt_id)
                .with_for_update()
            )
        ).one_or_none()
        if attempt_row is None:
            raise EvidenceNotFound("committed attempt and self-review were not found")
        activity, attempt, self_review = attempt_row
        if activity.state not in {
            "self_review_complete",
            "ai_processing",
            "feedback_ready",
            "correction_due",
            "demonstrated",
            "needs_work",
        }:
            raise EvidenceConflict("attempt is not ready for external evaluation")
        try:
            attempt_payload = json.loads(attempt.original_text or "")
            task_context = attempt_payload["task_context"]
            output = attempt_payload["output"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise EvidenceConflict("committed attempt lineage is invalid") from exc
        if (
            task_context.get("exercise_type") != command.exercise_type
            or task_context.get("mapping_version") != command.mapping_version
        ):
            raise EvidenceConflict("attempt exercise lineage does not match")

        exercise = await self._session.scalar(
            select(ExerciseTypeVersion)
            .where(ExerciseTypeVersion.owner_id == owner_id)
            .where(ExerciseTypeVersion.config_seed_version_id == config.id)
            .where(ExerciseTypeVersion.exercise_type == command.exercise_type)
            .where(ExerciseTypeVersion.mapping_version == command.mapping_version)
            .with_for_update(read=True, key_share=True)
        )
        rubric = await self._session.scalar(
            select(RubricVersion)
            .where(RubricVersion.owner_id == owner_id)
            .where(RubricVersion.config_seed_version_id == config.id)
            .where(RubricVersion.rubric_key == command.rubric_slug)
            .where(RubricVersion.version_key == command.rubric_version)
            .with_for_update(read=True, key_share=True)
        )
        if exercise is None or rubric is None:
            raise EvidenceNotFound("exercise or rubric version was not found")

        dimension_rows = tuple(
            (
                await self._session.scalars(
                    select(RubricDimension)
                    .where(RubricDimension.owner_id == owner_id)
                    .where(RubricDimension.config_seed_version_id == config.id)
                    .where(RubricDimension.rubric_version_id == rubric.id)
                    .order_by(RubricDimension.ordinal, RubricDimension.id)
                )
            ).all()
        )
        skill_rows = tuple(
            (
                await self._session.scalars(
                    select(Competency)
                    .where(Competency.owner_id == owner_id)
                    .where(Competency.config_seed_version_id == config.id)
                    .order_by(Competency.id)
                )
            ).all()
        )
        if {item.dimension_key for item in dimension_rows} != {
            item.slug for item in rubric_config.dimensions
        } or {item.slug for item in skill_rows} != {item.slug for item in bundle.skills}:
            raise EvidenceConflict("persisted configuration rows do not match their payload")

        artifact_rows = (
            await self._session.execute(
                select(Artifact.id, Artifact.artifact_class)
                .join(
                    ActivityArtifactLink,
                    (ActivityArtifactLink.owner_id == Artifact.owner_id)
                    & (ActivityArtifactLink.artifact_id == Artifact.id),
                )
                .where(ActivityArtifactLink.owner_id == owner_id)
                .where(ActivityArtifactLink.activity_instance_id == activity.id)
                .where(ActivityArtifactLink.attempt_id == attempt.id)
                .order_by(Artifact.id)
            )
        ).all()
        if command.observation_ids:
            raise EvidenceInvalidRequest(
                "observation references are unavailable until analysis storage is installed"
            )
        selected: str | None = None
        selector_field: str | None = None
        for field_name in ("domain_competency_slug", "story_competency_slug"):
            value = output.get(field_name) if isinstance(output, dict) else None
            if value is not None:
                if selected is not None or not isinstance(value, str):
                    raise EvidenceConflict("committed precommit selector is invalid")
                selected = value
                selector_field = field_name
        return EvaluationContext(
            config_seed_version_id=config.id,
            config_version_key=config.version_key,
            formula=bundle.formula,
            exercise=exercise_config,
            exercise_type_version_id=exercise.id,
            rubric=rubric_config,
            rubric_version_id=rubric.id,
            dimensions=tuple(
                PersistedDimension(
                    id=item.id,
                    slug=item.dimension_key,
                    weight=item.weight,
                    maximum=item.max_score,
                )
                for item in dimension_rows
            ),
            skills={
                item.slug: PersistedSkill(
                    id=item.id,
                    slug=item.slug,
                    baseline=item.baseline_level,
                    month_one_target=item.month_one_target,
                    final_target=item.final_target,
                )
                for item in skill_rows
            },
            activity_id=activity.id,
            attempt_id=attempt.id,
            attempt_kind=attempt.attempt_kind,
            attempt_assistance_mode=attempt.assistance_mode,
            attempt_committed_at=attempt.committed_at,
            self_review_submitted_at=self_review.submitted_at,
            prompt=attempt.prompt,
            selected_competency=selected,
            selector_field=selector_field,
            selector_committed_in_attempt=selected is not None,
            self_score=self_review.self_score,
            linked_artifact_classes={item[0]: item[1] for item in artifact_rows},
            written_output_available=(
                attempt.original_markdown is not None or attempt.original_sql is not None
            ),
        )

    async def _save_evaluation(
        self, *, owner_id: int, prepared: PreparedEvaluation, now: datetime
    ) -> RubricEvaluation:
        evaluation = RubricEvaluation(
            owner_id=owner_id,
            config_seed_version_id=prepared.config_seed_version_id,
            activity_instance_id=prepared.activity_id,
            attempt_id=prepared.attempt_id,
            rubric_version_id=prepared.rubric_version_id,
            evaluator_kind=prepared.evaluator,
            evaluation_schema_version=1,
            input_manifest={
                "schema_version": 1,
                "artifact_ids": list(prepared.input_artifact_ids),
                "observation_ids": list(prepared.input_observation_ids),
            },
            evaluated_at=prepared.evaluated_at,
            created_at=now,
        )
        self._session.add(evaluation)
        await self._session.flush()
        return evaluation

    async def _save_dimension_scores(
        self,
        *,
        owner_id: int,
        evaluation: RubricEvaluation,
        prepared: PreparedEvaluation,
        now: datetime,
    ) -> dict[str, RubricDimensionScore]:
        rows: dict[str, RubricDimensionScore] = {}
        for item in prepared.dimensions:
            row = RubricDimensionScore(
                owner_id=owner_id,
                config_seed_version_id=prepared.config_seed_version_id,
                rubric_evaluation_id=evaluation.id,
                rubric_version_id=prepared.rubric_version_id,
                rubric_dimension_id=item.dimension_id,
                availability=item.availability,
                score=item.score,
                weight_used=item.weight,
                evidence_manifest={
                    "schema_version": 1,
                    "artifact_ids": list(item.artifact_ids),
                    "observation_ids": list(item.observation_ids),
                },
                created_at=now,
            )
            self._session.add(row)
            rows[item.dimension_slug] = row
        await self._session.flush()
        return rows

    async def _save_skill_events(
        self,
        *,
        owner_id: int,
        evaluation: RubricEvaluation,
        dimension_rows: dict[str, RubricDimensionScore],
        prepared: PreparedEvaluation,
        now: datetime,
    ) -> tuple[SkillEvidenceEvent, ...]:
        rows: list[SkillEvidenceEvent] = []
        prepared_dimensions = {item.dimension_slug: item for item in prepared.dimensions}
        for item in prepared.skill_events:
            manifest_scores: list[dict[str, int | float]] = []
            dimension_score_ids: list[int] = []
            for slug in item.dimension_slugs:
                dimension = prepared_dimensions[slug]
                score_row = dimension_rows[slug]
                assert dimension.score is not None and dimension.weight is not None
                manifest_scores.append(
                    {
                        "dimension_score_id": score_row.id,
                        "score": _json_number(dimension.score),
                        "weight": _json_number(dimension.weight),
                    }
                )
                dimension_score_ids.append(score_row.id)
            row = SkillEvidenceEvent(
                owner_id=owner_id,
                config_seed_version_id=prepared.config_seed_version_id,
                activity_instance_id=prepared.activity_id,
                attempt_id=prepared.attempt_id,
                rubric_evaluation_id=evaluation.id,
                rubric_version_id=prepared.rubric_version_id,
                exercise_type_version_id=prepared.exercise_type_version_id,
                competency_id=item.skill_id,
                formula_version=prepared.formula.version,
                practice_mode=prepared.exercise.evidence_mode,
                assistance_code=prepared.assistance,
                evaluator_kind=prepared.evaluator,
                difficulty_code=prepared.difficulty,
                raw_dimension_scores={"schema_version": 1, "scores": manifest_scores},
                raw_score_numerator=item.raw_score_numerator,
                raw_score_denominator=item.raw_score_denominator,
                performance_score=item.performance_score,
                exercise_skill_impact=item.skill_impact,
                practice_mode_factor=item.practice_mode_factor,
                ai_independence_factor=item.assistance_factor,
                evaluator_confidence_factor=item.evaluator_factor,
                difficulty_factor=item.difficulty_factor,
                effective_weight=item.effective_weight,
                qualifying_for_level=item.qualifying_for_level,
                qualification_reason_code=item.qualification_reason,
                explanation={
                    "schema_version": 1,
                    "summary_code": item.summary_code,
                    "dimension_score_ids": dimension_score_ids,
                    "discount_codes": list(item.discount_codes),
                },
                occurred_at=prepared.evaluated_at,
                created_at=now,
            )
            self._session.add(row)
            rows.append(row)
        await self._session.flush()
        return tuple(rows)

    async def _skill_evidence(
        self,
        *,
        owner_id: int,
        config_seed_version_id: int,
        skill_id: int,
        formula_version: str,
    ) -> tuple[SkillEvidence, ...]:
        rows = (
            await self._session.execute(
                select(
                    SkillEvidenceEvent,
                    ExerciseTypeVersion.exercise_type,
                    Attempt.prompt,
                    Attempt.attempt_kind,
                    RubricEvaluation.input_manifest,
                )
                .join(
                    ExerciseTypeVersion,
                    (ExerciseTypeVersion.owner_id == SkillEvidenceEvent.owner_id)
                    & (
                        ExerciseTypeVersion.config_seed_version_id
                        == SkillEvidenceEvent.config_seed_version_id
                    )
                    & (
                        ExerciseTypeVersion.id
                        == SkillEvidenceEvent.exercise_type_version_id
                    ),
                )
                .join(
                    Attempt,
                    (Attempt.owner_id == SkillEvidenceEvent.owner_id)
                    & (
                        Attempt.activity_instance_id
                        == SkillEvidenceEvent.activity_instance_id
                    )
                    & (Attempt.id == SkillEvidenceEvent.attempt_id),
                )
                .join(
                    RubricEvaluation,
                    (RubricEvaluation.owner_id == SkillEvidenceEvent.owner_id)
                    & (
                        RubricEvaluation.config_seed_version_id
                        == SkillEvidenceEvent.config_seed_version_id
                    )
                    & (RubricEvaluation.id == SkillEvidenceEvent.rubric_evaluation_id),
                )
                .where(SkillEvidenceEvent.owner_id == owner_id)
                .where(
                    SkillEvidenceEvent.config_seed_version_id
                    == config_seed_version_id
                )
                .where(SkillEvidenceEvent.competency_id == skill_id)
                .where(SkillEvidenceEvent.formula_version == formula_version)
                .order_by(SkillEvidenceEvent.occurred_at, SkillEvidenceEvent.id)
            )
        ).all()
        artifact_ids = {
            artifact_id
            for row in rows
            for artifact_id in row[4].get("artifact_ids", [])
            if isinstance(artifact_id, int)
        }
        artifact_classes: dict[int, str] = (
            {
                artifact_id: artifact_class
                for artifact_id, artifact_class in (
                    await self._session.execute(
                        select(Artifact.id, Artifact.artifact_class)
                        .where(Artifact.owner_id == owner_id)
                        .where(Artifact.id.in_(artifact_ids))
                    )
                ).all()
            }
            if artifact_ids
            else {}
        )
        result: list[SkillEvidence] = []
        for event, exercise_type, prompt, attempt_kind, manifest in rows:
            input_ids = tuple(
                item for item in manifest.get("artifact_ids", []) if isinstance(item, int)
            )
            result.append(
                SkillEvidence(
                    event_id=event.id,
                    performance_score=event.performance_score,
                    effective_weight=event.effective_weight,
                    qualifying_for_level=event.qualifying_for_level,
                    exercise_type=exercise_type,
                    scenario_key=hashlib.sha256(prompt.encode()).hexdigest(),
                    occurred_at=event.occurred_at,
                    practice_mode=event.practice_mode,
                    attempt_kind=attempt_kind,
                    reviewed_artifact=bool(input_ids),
                    scored_recording=any(
                        artifact_classes.get(item) == "original_audio" for item in input_ids
                    ),
                )
            )
        return tuple(result)

    async def _save_snapshot(
        self,
        *,
        owner_id: int,
        skill_id: int,
        prepared: PreparedEvaluation,
        now: datetime,
    ) -> SkillSnapshot:
        skill = await self._session.scalar(
            select(Competency)
            .where(Competency.owner_id == owner_id)
            .where(Competency.config_seed_version_id == prepared.config_seed_version_id)
            .where(Competency.id == skill_id)
            .with_for_update()
        )
        if skill is None:
            raise EvidenceConflict("snapshot skill lineage was not found")
        evidence = await self._skill_evidence(
            owner_id=owner_id,
            config_seed_version_id=prepared.config_seed_version_id,
            skill_id=skill_id,
            formula_version=prepared.formula.version,
        )
        estimate = estimate_skill(
            baseline=skill.baseline_level,
            month_one_target=skill.month_one_target,
            final_target=skill.final_target,
            events=evidence,
            formula=prepared.formula,
            as_of=prepared.evaluated_at,
        )
        evidence_by_id = {item.event_id: item for item in evidence}
        manifest = [
            {
                "event_id": item.event_id,
                "effective_weight": _json_number(item.used_weight),
                "inclusion_code": item.inclusion,
            }
            for item in estimate.weight_manifest
        ]
        remaining = _SNAPSHOT_MANIFEST_LIMIT - len(manifest)
        excluded = sorted(
            (
                evidence_by_id[item]
                for item in estimate.excluded_event_ids
                if item in evidence_by_id
            ),
            key=lambda item: (item.occurred_at, str(item.event_id)),
            reverse=True,
        )[:remaining]
        manifest.extend(
            {
                "event_id": item.event_id,
                "effective_weight": 0,
                "inclusion_code": (
                    "excluded_outside_window"
                    if item.qualifying_for_level
                    else "excluded_nonqualifying"
                ),
            }
            for item in excluded
        )
        if estimate.trend.code == "insufficient_evidence":
            trend_basis_code = (
                "no_qualifying_evidence"
                if not estimate.contributing_event_ids
                else "too_few_events"
            )
        else:
            trend_basis_code = estimate.trend.code
        snapshot_date = prepared.evaluated_at.date()
        prior_sequence = await self._session.scalar(
            select(func.coalesce(func.max(SkillSnapshot.snapshot_sequence), 0))
            .where(SkillSnapshot.owner_id == owner_id)
            .where(SkillSnapshot.competency_id == skill_id)
            .where(SkillSnapshot.formula_version == prepared.formula.version)
            .where(SkillSnapshot.snapshot_date == snapshot_date)
        )
        sequence = (prior_sequence or 0) + 1
        snapshot = SkillSnapshot(
            owner_id=owner_id,
            config_seed_version_id=prepared.config_seed_version_id,
            competency_id=skill_id,
            formula_version=prepared.formula.version,
            snapshot_date=snapshot_date,
            snapshot_sequence=sequence,
            estimated_level=estimate.estimate,
            confidence_code=estimate.confidence.code,
            trend_code=estimate.trend.code,
            recency_code=(
                "no_qualifying_evidence"
                if estimate.recency.code == "no_evidence"
                else estimate.recency.code
            ),
            baseline_target_gap=(skill.baseline_level - estimate.estimate).quantize(
                _SCORE_QUANTUM, rounding=ROUND_HALF_UP
            ),
            month_one_target_gap=estimate.month_one_target_gap,
            final_target_gap=estimate.final_target_gap,
            total_effective_weight=estimate.total_effective_weight,
            qualifying_event_count=estimate.qualifying_event_count,
            exercise_type_count=estimate.confidence.exercise_type_count,
            last_strong_evidence_date=(
                estimate.last_strong_evidence_at.date()
                if estimate.last_strong_evidence_at is not None
                else None
            ),
            contributing_event_manifest={"schema_version": 1, "events": manifest},
            confidence_basis={
                "schema_version": 1,
                "basis_code": estimate.confidence.basis_code,
                "event_ids": list(estimate.confidence.event_ids),
            },
            trend_basis={
                "schema_version": 1,
                "basis_code": trend_basis_code,
                "event_ids": list(estimate.trend.event_ids),
            },
            created_at=now,
        )
        self._session.add(snapshot)
        await self._session.flush()
        return snapshot

    async def _save_portfolio_score(
        self,
        *,
        owner_id: int,
        evaluation: RubricEvaluation,
        prepared: PreparedEvaluation,
        now: datetime,
    ) -> PortfolioJudgmentScore | None:
        if prepared.portfolio_components is None:
            return None
        history_rows = tuple(
            (
                await self._session.scalars(
                    select(PortfolioJudgmentScore)
                    .where(PortfolioJudgmentScore.owner_id == owner_id)
                    .where(
                        PortfolioJudgmentScore.config_seed_version_id
                        == prepared.config_seed_version_id
                    )
                    .where(
                        PortfolioJudgmentScore.formula_version
                        == prepared.formula.version
                    )
                    .order_by(
                        PortfolioJudgmentScore.scored_at,
                        PortfolioJudgmentScore.id,
                    )
                )
            ).all()
        )
        scored = score_portfolio_judgment(
            component_scores=prepared.portfolio_components,
            rubric=prepared.rubric,
            formula_version=prepared.formula.version,
            exercise_type=prepared.exercise.slug,
            mapping_version=prepared.exercise.mapping_version,
            history=tuple(
                PortfolioHistoryItem(item.id, item.total_score, item.scored_at)
                for item in history_rows
            ),
        )
        trend_event_ids: tuple[int | str, ...]
        if scored.trend.code == "insufficient_evidence":
            basis_code = "too_few_events"
            trend_event_ids = tuple(item.id for item in history_rows)
        else:
            basis_code = scored.trend.code
            trend_event_ids = scored.trend.event_ids
        components = {item.slug: item.score for item in scored.components}
        row = PortfolioJudgmentScore(
            owner_id=owner_id,
            config_seed_version_id=prepared.config_seed_version_id,
            activity_instance_id=prepared.activity_id,
            attempt_id=prepared.attempt_id,
            rubric_evaluation_id=evaluation.id,
            rubric_version_id=prepared.rubric_version_id,
            formula_version=prepared.formula.version,
            impact_risk_assessment=components["impact_risk_assessment"],
            explicit_prioritization=components["explicit_prioritization"],
            delegation_ownership=components["delegation_ownership"],
            communication_control=components["communication_control"],
            proactive_work_protection=components["proactive_work_protection"],
            evidence_based_reprioritization=components[
                "evidence_based_reprioritization"
            ],
            english_clarity=components["english_clarity"],
            total_score=scored.total_score,
            trend_basis={
                "schema_version": 1,
                "basis_code": basis_code,
                "event_ids": list(trend_event_ids),
            },
            scored_at=prepared.evaluated_at,
            created_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def _save_audit_and_outbox(
        self,
        *,
        owner_id: int,
        evaluation_id: int,
        activity_id: int,
        event_count: int,
        idempotency_key: str,
        now: datetime,
    ) -> None:
        idempotency_hash = hashlib.sha256(idempotency_key.encode()).digest()
        self._session.add(
            AuditEvent(
                owner_id=owner_id,
                actor_kind="system",
                actor_subject_hash=hashlib.sha256(
                    f"evidence-worker:{owner_id}".encode()
                ).digest(),
                action="evidence.recorded",
                aggregate_type="activity",
                aggregate_id=str(activity_id),
                request_correlation_hash=None,
                idempotency_correlation_hash=idempotency_hash,
                redacted_metadata=AuditMetadataV1(
                    outcome=AuditOutcome.SUCCEEDED,
                    reason_code=AuditReasonCode.NONE,
                    counts={AuditCountKey.AFFECTED: event_count},
                    flags={
                        AuditFlagKey.AUTHENTICATED: True,
                        AuditFlagKey.AUTHORIZED: True,
                        AuditFlagKey.REDACTED: True,
                    },
                ).to_payload(),
                occurred_at=now,
            )
        )
        self._session.add(
            OutboxEvent(
                owner_id=owner_id,
                aggregate_type="activity",
                aggregate_id=activity_id,
                event_type="evidence.recorded",
                payload_schema_version=1,
                payload={
                    "schema_version": 1,
                    "subject_id": evaluation_id,
                    "related_id": activity_id,
                },
                occurred_at=now,
                published_at=None,
                attempts=0,
                idempotency_key=f"evidence:{idempotency_hash.hex()}",
            )
        )
        await self._session.flush()

    async def list_skills(self, *, owner_id: int) -> SkillListResponse:
        config_id = await self._latest_config_id(owner_id)
        skills = tuple(
            (
                await self._session.scalars(
                    select(Competency)
                    .where(Competency.owner_id == owner_id)
                    .where(Competency.config_seed_version_id == config_id)
                    .order_by(Competency.slug, Competency.id)
                )
            ).all()
        )
        snapshots = tuple(
            (
                await self._session.scalars(
                    select(SkillSnapshot)
                    .where(SkillSnapshot.owner_id == owner_id)
                    .where(SkillSnapshot.config_seed_version_id == config_id)
                    .order_by(
                        SkillSnapshot.competency_id,
                        SkillSnapshot.created_at.desc(),
                        SkillSnapshot.id.desc(),
                    )
                )
            ).all()
        )
        latest: dict[int, SkillSnapshot] = {}
        for item in snapshots:
            latest.setdefault(item.competency_id, item)
        result = SkillListResponse(
            items=tuple(
                SkillSummaryResponse(
                    slug=item.slug,
                    name=item.name,
                    baseline=item.baseline_level,
                    month_one_target=item.month_one_target,
                    final_target=item.final_target,
                    latest_snapshot=(
                        self._snapshot_response(latest[item.id])
                        if item.id in latest
                        else None
                    ),
                )
                for item in skills
            )
        )
        await self._session.rollback()
        return result

    async def get_skill(self, *, owner_id: int, skill_slug: str) -> SkillSummaryResponse:
        items = (await self.list_skills(owner_id=owner_id)).items
        for item in items:
            if item.slug == skill_slug:
                return item
        raise EvidenceNotFound("skill was not found")

    async def list_skill_evidence(
        self,
        *,
        owner_id: int,
        skill_slug: str,
        cursor: int | None,
        limit: int,
    ) -> EvidenceEventPage:
        return await self._list_evidence(
            owner_id=owner_id,
            skill_slug=skill_slug,
            activity_id=None,
            cursor=cursor,
            limit=limit,
        )

    async def list_activity_evidence(
        self,
        *,
        owner_id: int,
        activity_id: int,
        cursor: int | None,
        limit: int,
    ) -> EvidenceEventPage:
        return await self._list_evidence(
            owner_id=owner_id,
            skill_slug=None,
            activity_id=activity_id,
            cursor=cursor,
            limit=limit,
        )

    async def _list_evidence(
        self,
        *,
        owner_id: int,
        skill_slug: str | None,
        activity_id: int | None,
        cursor: int | None,
        limit: int,
    ) -> EvidenceEventPage:
        if not 1 <= limit <= _READ_LIMIT_MAX:
            raise EvidenceInvalidRequest("evidence page limit is invalid")
        query = (
            select(
                SkillEvidenceEvent,
                Competency.slug,
                ExerciseTypeVersion.exercise_type,
                ExerciseTypeVersion.mapping_version,
                RubricVersion.rubric_key,
                RubricVersion.version_key,
            )
            .join(
                Competency,
                (Competency.owner_id == SkillEvidenceEvent.owner_id)
                & (
                    Competency.config_seed_version_id
                    == SkillEvidenceEvent.config_seed_version_id
                )
                & (Competency.id == SkillEvidenceEvent.competency_id),
            )
            .join(
                ExerciseTypeVersion,
                (ExerciseTypeVersion.owner_id == SkillEvidenceEvent.owner_id)
                & (
                    ExerciseTypeVersion.config_seed_version_id
                    == SkillEvidenceEvent.config_seed_version_id
                )
                & (ExerciseTypeVersion.id == SkillEvidenceEvent.exercise_type_version_id),
            )
            .join(
                RubricVersion,
                (RubricVersion.owner_id == SkillEvidenceEvent.owner_id)
                & (
                    RubricVersion.config_seed_version_id
                    == SkillEvidenceEvent.config_seed_version_id
                )
                & (RubricVersion.id == SkillEvidenceEvent.rubric_version_id),
            )
            .where(SkillEvidenceEvent.owner_id == owner_id)
        )
        if skill_slug is not None:
            query = query.where(Competency.slug == skill_slug)
        if activity_id is not None:
            query = query.where(SkillEvidenceEvent.activity_instance_id == activity_id)
        if cursor is not None:
            query = query.where(SkillEvidenceEvent.id < cursor)
        rows = (
            await self._session.execute(
                query.order_by(SkillEvidenceEvent.id.desc()).limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        selected = rows[:limit]
        result = EvidenceEventPage(
            items=tuple(
                EvidenceEventResponse(
                    id=event.id,
                    activity_id=event.activity_instance_id,
                    attempt_id=event.attempt_id,
                    skill_slug=skill,
                    exercise_type=exercise_type,
                    mapping_version=mapping_version,
                    formula_version=event.formula_version,
                    rubric_slug=rubric_slug,
                    rubric_version=rubric_version,
                    evaluator=event.evaluator_kind,
                    practice_mode=event.practice_mode,
                    assistance=event.assistance_code,
                    difficulty=event.difficulty_code,
                    performance_score=event.performance_score,
                    skill_impact=event.exercise_skill_impact,
                    effective_weight=event.effective_weight,
                    qualifying_for_level=event.qualifying_for_level,
                    qualification_reason=event.qualification_reason_code,
                    raw_dimension_scores=event.raw_dimension_scores,
                    occurred_at=event.occurred_at,
                )
                for (
                    event,
                    skill,
                    exercise_type,
                    mapping_version,
                    rubric_slug,
                    rubric_version,
                ) in selected
            ),
            next_cursor=selected[-1][0].id if has_more and selected else None,
        )
        await self._session.rollback()
        return result

    async def portfolio_history(
        self,
        *,
        owner_id: int,
        cursor: int | None,
        limit: int,
    ) -> PortfolioHistoryResponse:
        if not 1 <= limit <= _READ_LIMIT_MAX:
            raise EvidenceInvalidRequest("portfolio page limit is invalid")
        query = (
            select(PortfolioJudgmentScore, RubricVersion.version_key)
            .join(
                RubricVersion,
                (RubricVersion.owner_id == PortfolioJudgmentScore.owner_id)
                & (
                    RubricVersion.config_seed_version_id
                    == PortfolioJudgmentScore.config_seed_version_id
                )
                & (RubricVersion.id == PortfolioJudgmentScore.rubric_version_id),
            )
            .where(PortfolioJudgmentScore.owner_id == owner_id)
        )
        if cursor is not None:
            query = query.where(PortfolioJudgmentScore.id < cursor)
        rows = (
            await self._session.execute(
                query.order_by(PortfolioJudgmentScore.id.desc()).limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        selected = rows[:limit]
        result = PortfolioHistoryResponse(
            items=tuple(
                self._portfolio_response(item, rubric_version)
                for item, rubric_version in selected
            ),
            next_cursor=selected[-1][0].id if has_more and selected else None,
        )
        await self._session.rollback()
        return result

    async def _latest_config_id(self, owner_id: int) -> int:
        config_id = await self._session.scalar(
            select(ConfigSeedVersion.id)
            .where(ConfigSeedVersion.owner_id == owner_id)
            .order_by(ConfigSeedVersion.id.desc())
            .limit(1)
        )
        if config_id is None:
            raise EvidenceNotFound("scoring configuration was not found")
        return config_id

    @staticmethod
    def _snapshot_response(item: SkillSnapshot) -> SkillSnapshotResponse:
        return SkillSnapshotResponse(
            id=item.id,
            formula_version=item.formula_version,
            snapshot_date=item.snapshot_date,
            estimated_level=item.estimated_level,
            confidence=item.confidence_code,
            trend=item.trend_code,
            recency=item.recency_code,
            baseline_target_gap=item.baseline_target_gap,
            month_one_target_gap=item.month_one_target_gap,
            final_target_gap=item.final_target_gap,
            total_effective_weight=item.total_effective_weight,
            qualifying_event_count=item.qualifying_event_count,
            exercise_type_count=item.exercise_type_count,
            last_strong_evidence_date=item.last_strong_evidence_date,
            manifest=tuple(
                SnapshotManifestItem.model_validate(event)
                for event in item.contributing_event_manifest["events"]
            ),
            confidence_basis=item.confidence_basis,
            trend_basis=item.trend_basis,
        )

    @staticmethod
    def _portfolio_response(
        item: PortfolioJudgmentScore, rubric_version: str
    ) -> PortfolioScoreResponse:
        return PortfolioScoreResponse(
            id=item.id,
            activity_id=item.activity_instance_id,
            attempt_id=item.attempt_id,
            formula_version=item.formula_version,
            rubric_version=rubric_version,
            total_score=item.total_score,
            components=tuple(
                PortfolioComponentResponse(slug=slug, score=getattr(item, slug))
                for slug in (
                    "impact_risk_assessment",
                    "explicit_prioritization",
                    "delegation_ownership",
                    "communication_control",
                    "proactive_work_protection",
                    "evidence_based_reprioritization",
                    "english_clarity",
                )
            ),
            trend_basis=item.trend_basis,
            scored_at=item.scored_at,
        )
