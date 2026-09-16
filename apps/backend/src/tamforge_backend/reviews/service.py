"""AI reviews: queue a committed, self-reviewed attempt, score it, record the evidence.

The worker sweeps activities that finished their self-review and queues one
`claude_review` job each. Processing builds the reviewer's request from the task
brief, the block's rubric, the committed attempt, the self-review and, when the
learner recorded the attempt, the speaker turns and metrics the speech worker
produced. The outcome is stored on the activity, the rubric scores are recorded
through the evidence ledger so the mapped skills move, and the activity becomes
`feedback_ready`. A review that cannot be recorded as evidence is still shown to
the learner, with the reason, so nothing is silently lost.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.reviewer import (
    REVIEW_PROMPT_VERSION,
    ReviewBlock,
    ReviewDimension,
    ReviewerService,
    ReviewerUnavailable,
    ReviewOutcome,
    ReviewRequest,
)
from ..database import transaction_scope
from ..evidence.config_loader import load_config_payload
from ..evidence.config_models import ConfigBundle
from ..evidence.models import ConfigSeedVersion
from ..evidence.schemas import (
    DimensionEvaluationInput,
    EvidenceEvaluationCommand,
    SkillDimensionSubsetInput,
)
from ..evidence.scoring import resolve_skill_impact
from ..evidence.service import EvidenceError, EvidenceService
from ..jobs.repository import SqlAlchemyJobRepository
from ..jobs.schemas import EnqueueJobCommand, JobResponse, ReferencePayload
from ..jobs.service import JobService
from ..learning.enums import ActivityState
from ..learning.models import ActivityInstance, Attempt, SelfReview, StudyDay
from ..learning.state_machine import ActivityStateError, transition
from ..models.base import utc_now
from ..notifications.models import BackgroundJob, OutboxEvent
from ..recordings.models import Recording
from ..roadmaps.models import TaskDefinition
from ..speech.jobs import CLAUDE_ANALYSIS_PRIORITY
from ..speech.models import SpeechAnalysis
from ..today.models import ActivityProcessingStatus
from .models import ActivityReview
from .schemas import ActivityReviewResponse, ReviewedDimensionResponse, ReviewFindingResponse

REVIEW_JOB_KIND = "claude_review"
REVIEW_MAX_ATTEMPTS = 3
BLOCK_RUBRIC_SLUG = "tam_block"


class ReviewsError(Exception):
    """Base error safe to convert to a closed public problem response."""


class ReviewNotFound(ReviewsError):
    """The owner-scoped activity does not exist."""


class ReviewConflict(ReviewsError):
    """The activity is not ready for a review, or already has one."""


class ReviewInvalid(ReviewsError):
    """The stored attempt cannot be reviewed; retrying will not help."""


class ReviewsUnavailable(ReviewsError):
    """The store or the reviewer cannot answer right now."""


def review_idempotency_key(*, activity_id: int, attempt_id: int) -> str:
    return f"claude-review-a{activity_id}-t{attempt_id}"


@dataclass(frozen=True, slots=True)
class _Loaded:
    activity: ActivityInstance
    day: StudyDay
    definition: TaskDefinition
    attempt: Attempt
    self_review: SelfReview


def assign_dimensions(
    dimensions: tuple[str, ...], skills: tuple[str, ...]
) -> dict[str, tuple[str, ...]]:
    """Give every mapped skill its own disjoint share of the rubric, round robin."""
    if not skills or len(skills) > len(dimensions):
        return {}
    return {
        skill: tuple(dimensions[j] for j in range(i, len(dimensions), len(skills)))
        for i, skill in enumerate(skills)
    }


class ReviewService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        reviewer: ReviewerService,
        evidence: EvidenceService | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._reviewer = reviewer
        self._evidence = evidence
        self._clock = clock

    # -- queueing -----------------------------------------------------------------

    async def enqueue_pending(self, *, limit: int = 20) -> int:
        """Queue a review for every self-reviewed activity that has none yet."""
        try:
            rows = (
                await self._session.execute(
                    select(ActivityInstance.owner_id, ActivityInstance.id, Attempt.id)
                    .join(
                        Attempt,
                        (Attempt.owner_id == ActivityInstance.owner_id)
                        & (Attempt.activity_instance_id == ActivityInstance.id),
                    )
                    .where(ActivityInstance.state == ActivityState.SELF_REVIEW_COMPLETE.value)
                    .where(Attempt.attempt_kind != "attempt_b")
                    .order_by(ActivityInstance.id)
                    .limit(limit)
                )
            ).all()
            await self._session.rollback()
            queued = 0
            for owner_id, activity_id, attempt_id in rows:
                if await self._request(owner_id=owner_id, activity_id=activity_id) is not None:
                    queued += 1
            return queued
        except SQLAlchemyError:
            raise ReviewsUnavailable("the review store is unavailable") from None

    async def request(self, *, owner_id: int, activity_id: int) -> ActivityReviewResponse:
        """Queue a review now for one activity; a queued or finished one replays."""
        try:
            await self._request(owner_id=owner_id, activity_id=activity_id, strict=True)
            return await self.read(owner_id=owner_id, activity_id=activity_id)
        except SQLAlchemyError:
            raise ReviewsUnavailable("the review store is unavailable") from None

    async def _request(
        self, *, owner_id: int, activity_id: int, strict: bool = False
    ) -> JobResponse | None:
        async with transaction_scope(self._session):
            loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            if loaded is None:
                if strict:
                    raise ReviewNotFound("the activity was not found")
                return None
            existing = await self._session.scalar(
                select(ActivityReview.id)
                .where(ActivityReview.owner_id == owner_id)
                .where(ActivityReview.activity_instance_id == activity_id)
            )
            if existing is not None:
                if strict:
                    raise ReviewConflict("the activity already has a review")
                return None
            state = ActivityState(loaded.activity.state)
            if state not in {ActivityState.SELF_REVIEW_COMPLETE, ActivityState.AI_PROCESSING}:
                if strict:
                    raise ReviewConflict("a review needs a committed, self-reviewed attempt")
                return None
            key = review_idempotency_key(activity_id=activity_id, attempt_id=loaded.attempt.id)
            pending = await self._session.scalar(
                select(BackgroundJob.id)
                .where(BackgroundJob.owner_id == owner_id)
                .where(BackgroundJob.idempotency_key == key)
                .where(BackgroundJob.state.in_(("queued", "running")))
            )
            if pending is not None and not strict:
                return None
            if state is ActivityState.SELF_REVIEW_COMPLETE:
                self._move(loaded, ActivityState.AI_PROCESSING)
            await self._status(owner_id, activity_id, "analyzing", None)
            await self._session.flush()
        result = await JobService(SqlAlchemyJobRepository(self._session)).enqueue(
            owner_id=owner_id,
            command=EnqueueJobCommand(
                kind=REVIEW_JOB_KIND,
                payload=ReferencePayload(subject_id=activity_id, related_id=loaded.attempt.id),
                priority=CLAUDE_ANALYSIS_PRIORITY,
                available_at=self._clock(),
                max_attempts=REVIEW_MAX_ATTEMPTS,
            ),
            idempotency_key=key,
        )
        return result.job

    # -- processing ---------------------------------------------------------------

    async def process(self, *, owner_id: int, activity_id: int) -> ActivityReview:
        """Score the attempt and record it; called by the Claude worker with a claimed job."""
        async with transaction_scope(self._session):
            loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            if loaded is None:
                raise ReviewInvalid("the activity or its self-reviewed attempt is missing")
            existing = await self._session.scalar(
                select(ActivityReview)
                .where(ActivityReview.owner_id == owner_id)
                .where(ActivityReview.activity_instance_id == activity_id)
            )
            if existing is not None:
                return existing
            bundle, config_version_key = await self._config(owner_id)
            request, output = await self._request_for(loaded, bundle)
        try:
            outcome = await self._reviewer.review(request)
        except ReviewerUnavailable as exc:
            raise ReviewsUnavailable(str(exc)) from None
        except RoleContractError as exc:
            raise ReviewInvalid(str(exc)) from None
        evidence_status, event_ids = await self._record_evidence(
            loaded=loaded,
            bundle=bundle,
            config_version_key=config_version_key,
            outcome=outcome,
            output=output,
        )
        async with transaction_scope(self._session):
            loaded = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            if loaded is None:
                raise ReviewInvalid("the activity vanished while it was being reviewed")
            now = self._clock()
            review = ActivityReview(
                owner_id=owner_id,
                activity_instance_id=activity_id,
                attempt_id=loaded.attempt.id,
                rubric_slug=request.rubric_slug,
                rubric_version=request.rubric_version,
                model=self._reviewer.model,
                prompt_version=REVIEW_PROMPT_VERSION,
                outcome=outcome.model_dump(mode="json"),
                evidence_status=evidence_status,
                evidence_event_ids=list(event_ids),
                created_at=now,
            )
            self._session.add(review)
            await self._session.flush()
            if ActivityState(loaded.activity.state) is ActivityState.SELF_REVIEW_COMPLETE:
                self._move(loaded, ActivityState.AI_PROCESSING)
                await self._session.flush()
            if ActivityState(loaded.activity.state) is ActivityState.AI_PROCESSING:
                self._move(loaded, ActivityState.FEEDBACK_READY)
            await self._status(owner_id, activity_id, "ready", None)
            self._session.add(
                OutboxEvent(
                    owner_id=owner_id,
                    aggregate_type="activity",
                    aggregate_id=activity_id,
                    event_type="activity.feedback_ready",
                    payload_schema_version=1,
                    payload={
                        "schema_version": 1,
                        "subject_id": activity_id,
                        "related_id": review.id,
                    },
                    occurred_at=now,
                    published_at=None,
                    attempts=0,
                    idempotency_key=f"feedback-ready:{review.id}",
                )
            )
            await self._session.flush()
            return review

    async def mark_failed(self, *, owner_id: int, activity_id: int, category: str) -> None:
        """Surface a parked job on the activity's processing status."""
        async with transaction_scope(self._session):
            await self._status(owner_id, activity_id, "needs_attention", category)

    # -- reading ------------------------------------------------------------------

    async def read(self, *, owner_id: int, activity_id: int) -> ActivityReviewResponse:
        try:
            activity = await self._session.scalar(
                select(ActivityInstance.id)
                .where(ActivityInstance.owner_id == owner_id)
                .where(ActivityInstance.id == activity_id)
            )
            if activity is None:
                raise ReviewNotFound("the activity was not found")
            review = await self._session.scalar(
                select(ActivityReview)
                .where(ActivityReview.owner_id == owner_id)
                .where(ActivityReview.activity_instance_id == activity_id)
            )
            job = await self._session.scalar(
                select(BackgroundJob)
                .where(BackgroundJob.owner_id == owner_id)
                .where(BackgroundJob.kind == REVIEW_JOB_KIND)
                .where(BackgroundJob.payload["subject_id"].as_integer() == activity_id)
                .order_by(BackgroundJob.id.desc())
                .limit(1)
            )
            bundle: ConfigBundle | None = None
            if review is not None:
                try:
                    bundle, _ = await self._config(owner_id)
                except ReviewInvalid:
                    bundle = None
            response = _response(activity_id, review, job, bundle)
            await self._session.rollback()
            return response
        except SQLAlchemyError:
            raise ReviewsUnavailable("the review store is unavailable") from None

    # -- internals ----------------------------------------------------------------

    async def _load(self, *, owner_id: int, activity_id: int, lock: bool) -> _Loaded | None:
        statement = (
            select(ActivityInstance, StudyDay, TaskDefinition, Attempt, SelfReview)
            .join(
                StudyDay,
                (StudyDay.owner_id == ActivityInstance.owner_id)
                & (StudyDay.id == ActivityInstance.study_day_id),
            )
            .join(
                TaskDefinition,
                (TaskDefinition.owner_id == ActivityInstance.owner_id)
                & (TaskDefinition.id == ActivityInstance.task_definition_id),
            )
            .join(
                SelfReview,
                (SelfReview.owner_id == ActivityInstance.owner_id)
                & (SelfReview.activity_instance_id == ActivityInstance.id),
            )
            .join(
                Attempt,
                (Attempt.owner_id == SelfReview.owner_id) & (Attempt.id == SelfReview.attempt_id),
            )
            .where(ActivityInstance.owner_id == owner_id)
            .where(ActivityInstance.id == activity_id)
            .order_by(SelfReview.id.desc())
            .limit(1)
        )
        if lock:
            statement = statement.with_for_update(of=ActivityInstance)
        row = (await self._session.execute(statement)).first()
        if row is None:
            return None
        activity, day, definition, attempt, self_review = row
        return _Loaded(activity, day, definition, attempt, self_review)

    def _move(self, loaded: _Loaded, target: ActivityState) -> None:
        try:
            decision = transition(
                current=ActivityState(loaded.activity.state),
                target=target,
                actual_version=loaded.activity.optimistic_version,
                expected_version=loaded.activity.optimistic_version,
                day_type=loaded.day.day_type,
                day_status=loaded.day.status,
            )
        except (ActivityStateError, ValueError) as exc:
            raise ReviewConflict(str(exc)) from None
        loaded.activity.state = decision.state.value
        loaded.activity.optimistic_version = decision.next_version

    async def _status(
        self, owner_id: int, activity_id: int, state: str, category: str | None
    ) -> None:
        label = "action_required" if state == "needs_attention" else state
        row = await self._session.scalar(
            select(ActivityProcessingStatus)
            .where(ActivityProcessingStatus.owner_id == owner_id)
            .where(ActivityProcessingStatus.activity_instance_id == activity_id)
            .with_for_update()
        )
        now = self._clock()
        if row is None:
            self._session.add(
                ActivityProcessingStatus(
                    owner_id=owner_id,
                    activity_instance_id=activity_id,
                    state=state,
                    progress_label=label,
                    last_error_category=category,
                    last_error_details=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.state = state
            row.progress_label = label
            row.last_error_category = category
            row.last_error_details = None
            row.updated_at = now

    async def _config(self, owner_id: int) -> tuple[ConfigBundle, str]:
        seeded = await self._session.scalar(
            select(ConfigSeedVersion)
            .where(ConfigSeedVersion.owner_id == owner_id)
            .order_by(ConfigSeedVersion.id.desc())
            .limit(1)
        )
        if seeded is None:
            raise ReviewInvalid("the scoring configuration is not seeded")
        try:
            bundle = load_config_payload(seeded.canonical_payload)
            bundle.rubric(BLOCK_RUBRIC_SLUG)
        except (KeyError, ValueError) as exc:
            raise ReviewInvalid(f"the seeded configuration has no block rubric: {exc}") from None
        return bundle, seeded.version_key

    async def _request_for(
        self, loaded: _Loaded, bundle: ConfigBundle
    ) -> tuple[ReviewRequest, dict[str, Any]]:
        rubric = bundle.rubric(BLOCK_RUBRIC_SLUG)
        payload = _attempt_payload(loaded.attempt)
        output = payload.get("output")
        if not isinstance(output, dict):
            raise ReviewInvalid("the committed attempt has no output to review")
        text = loaded.attempt.original_markdown or _render_output(output)
        transcript, metrics = await self._speech(loaded)
        review = loaded.self_review
        self_review = "\n".join(
            f"- {label}: {value}"
            for label, value in (
                ("Main answer", review.main_answer),
                ("Did well", review.did_well),
                ("Structure weakness", review.structure_weakness),
                ("Vague points", review.vague_points),
                ("Hesitation points", review.hesitation_points),
                ("Change next", review.change_next),
                ("Self-score", f"{review.self_score}/4"),
            )
        )
        request = ReviewRequest(
            block=ReviewBlock(
                stable_id=loaded.definition.stable_id,
                objective=loaded.definition.objective,
                required_output=_items(loaded.definition.output_contract),
                pass_criteria=_items(loaded.definition.pass_contract),
            ),
            rubric_slug=rubric.slug,
            rubric_version=rubric.version,
            dimensions=tuple(
                ReviewDimension(slug=item.slug, name=item.name, maximum=item.maximum)
                for item in rubric.dimensions
            ),
            committed_attempt=text,
            self_review=self_review,
            transcript=transcript,
            speech_metrics=metrics,
        )
        return request, output

    async def _speech(self, loaded: _Loaded) -> tuple[str | None, dict[str, Any] | None]:
        analysis = await self._session.scalar(
            select(SpeechAnalysis)
            .join(
                Recording,
                (Recording.owner_id == SpeechAnalysis.owner_id)
                & (Recording.id == SpeechAnalysis.recording_id),
            )
            .where(Recording.owner_id == loaded.activity.owner_id)
            .where(Recording.activity_instance_id == loaded.activity.id)
            .order_by(SpeechAnalysis.updated_at.desc())
            .limit(1)
        )
        if analysis is None or not analysis.turns:
            return None, None
        lines = []
        for turn in analysis.turns:
            seconds = int(cast(Any, turn.get("start_ms", 0))) // 1000
            speaker = "learner" if turn.get("speaker") == "learner" else "other"
            lines.append(f"{seconds // 60}:{seconds % 60:02d} {speaker}: {turn.get('text', '')}")
        return "\n".join(lines), dict(analysis.metrics)

    async def _record_evidence(
        self,
        *,
        loaded: _Loaded,
        bundle: ConfigBundle,
        config_version_key: str,
        outcome: ReviewOutcome,
        output: dict[str, Any],
    ) -> tuple[str, tuple[int, ...]]:
        if self._evidence is None:
            return "skipped: evidence recording is not configured", ()
        try:
            command = build_evidence_command(
                loaded=loaded,
                bundle=bundle,
                config_version_key=config_version_key,
                outcome=outcome,
                output=output,
                # Never before the evidence it judges, whatever the clocks say.
                evaluated_at=max(
                    self._clock(), loaded.attempt.committed_at, loaded.self_review.submitted_at
                ),
            )
        except ReviewInvalid as exc:
            return f"unrecorded: {exc}", ()
        try:
            recorded = await self._evidence.record(
                owner_id=loaded.activity.owner_id,
                command=command,
                idempotency_key=review_idempotency_key(
                    activity_id=loaded.activity.id, attempt_id=loaded.attempt.id
                ),
            )
        except EvidenceError as exc:
            await self._session.rollback()
            return f"unrecorded: {type(exc).__name__}: {exc}", ()
        return "recorded", tuple(recorded.evidence_event_ids)


def build_evidence_command(
    *,
    loaded: _Loaded,
    bundle: ConfigBundle,
    config_version_key: str,
    outcome: ReviewOutcome,
    output: dict[str, Any],
    evaluated_at: datetime,
) -> EvidenceEvaluationCommand:
    """The ledger command for a review: the rubric scores, split across the mapped skills."""
    payload = _attempt_payload(loaded.attempt)
    context = payload.get("task_context")
    if not isinstance(context, dict):
        raise ReviewInvalid("the committed attempt carries no task context")
    exercise_slug = str(context.get("exercise_type") or loaded.definition.exercise_type or "")
    try:
        exercise = bundle.exercise(exercise_slug)
    except KeyError:
        raise ReviewInvalid(
            f"exercise type {exercise_slug!r} is not in the configuration"
        ) from None
    rubric = bundle.rubric(BLOCK_RUBRIC_SLUG)
    written = bool(loaded.attempt.original_markdown or loaded.attempt.original_sql)
    conditions: set[str] = {"spoken_or_written_english"} if written else set()
    selector_field = exercise.required_precommit_field
    selected = None
    committed_selector = False
    if selector_field is not None:
        value = output.get(selector_field)
        selected = str(value) if isinstance(value, str) and value else None
        committed_selector = selected is not None
        if committed_selector:
            conditions.add("reviewed_dynamic_impact")
    skills: list[str] = []
    for impact in exercise.impacts:
        resolved = resolve_skill_impact(
            exercise=exercise,
            skill_slug=impact.skill_slug,
            conditions_met=frozenset(conditions),
            selected_competency=selected,
            selector_committed_before_attempt=committed_selector,
        )
        if resolved.weight > 0:
            skills.append(impact.skill_slug)
    if selected is not None and selected not in skills:
        resolved = resolve_skill_impact(
            exercise=exercise,
            skill_slug=selected,
            conditions_met=frozenset(conditions),
            selected_competency=selected,
            selector_committed_before_attempt=committed_selector,
        )
        if resolved.weight > 0:
            skills.append(selected)
    scores = {item.slug: item.score for item in outcome.dimensions}
    subsets = assign_dimensions(tuple(d.slug for d in rubric.dimensions), tuple(skills))
    if skills and not subsets:
        raise ReviewInvalid("more mapped skills than rubric dimensions")
    assistance = (
        "ai_hints_during_attempt"
        if loaded.attempt.assistance_mode == "hint_ladder"
        else "ai_after_committed_attempt"
    )
    return EvidenceEvaluationCommand(
        activity_id=loaded.activity.id,
        attempt_id=loaded.attempt.id,
        config_version_key=config_version_key,
        exercise_type=exercise.slug,
        mapping_version=exercise.mapping_version,
        formula_version=bundle.formula.version,
        rubric_slug=rubric.slug,
        rubric_version=rubric.version,
        practice_mode=exercise.evidence_mode,
        assistance=cast(Any, assistance),
        evaluator="ai_rubric_reviewer",
        difficulty="standard",
        ai_role="reviewer",
        evaluated_at=evaluated_at,
        artifact_ids=(),
        observation_ids=(),
        transcript_available=False,
        audio_available=False,
        written_english_available=written,
        scored_recording=False,
        dimensions=tuple(
            DimensionEvaluationInput(
                dimension_slug=item.slug,
                availability="scored",
                score=min(item.maximum, scores.get(item.slug, Decimal(0))),
            )
            for item in rubric.dimensions
        ),
        skill_dimension_subsets=tuple(
            SkillDimensionSubsetInput(skill_slug=skill, dimension_slugs=dims)
            for skill, dims in subsets.items()
        ),
    )


def _attempt_payload(attempt: Attempt) -> dict[str, Any]:
    try:
        payload = json.loads(attempt.original_text or "")
    except json.JSONDecodeError:
        return {"output": {"text": attempt.original_text or ""}}
    return payload if isinstance(payload, dict) else {"output": {"text": str(payload)}}


def _render_output(output: dict[str, Any]) -> str:
    parts = []
    for key, value in output.items():
        if isinstance(value, str) and value.strip():
            parts.append(f"{key.replace('_', ' ')}:\n{value.strip()}")
        elif isinstance(value, list) and value:
            parts.append(f"{key.replace('_', ' ')}:\n" + "\n".join(f"- {item}" for item in value))
    return "\n\n".join(parts) if parts else json.dumps(output, ensure_ascii=False)


def _items(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()
    values = payload.get("items")
    if not isinstance(values, list):
        return ()
    return tuple(str(item) for item in values if isinstance(item, str))


def _response(
    activity_id: int,
    review: ActivityReview | None,
    job: BackgroundJob | None,
    bundle: ConfigBundle | None,
) -> ActivityReviewResponse:
    if review is None:
        if job is None:
            return ActivityReviewResponse(activity_id=activity_id, status="not_requested")
        if job.state in {"queued", "running"}:
            return ActivityReviewResponse(activity_id=activity_id, status=cast(Any, job.state))
        if job.state == "succeeded":
            return ActivityReviewResponse(activity_id=activity_id, status="running")
        return ActivityReviewResponse(
            activity_id=activity_id,
            status="needs_attention",
            failure_category=job.last_error_category,
        )
    names: dict[str, tuple[str, Decimal]] = {}
    if bundle is not None:
        try:
            names = {
                d.slug: (d.name, d.maximum) for d in bundle.rubric(review.rubric_slug).dimensions
            }
        except KeyError:
            names = {}
    outcome = ReviewOutcome.model_validate(review.outcome)
    return ActivityReviewResponse(
        activity_id=activity_id,
        status="ready",
        review_id=review.id,
        attempt_id=review.attempt_id,
        rubric_slug=review.rubric_slug,
        rubric_version=review.rubric_version,
        model=review.model,
        verdict=outcome.verdict,
        dimensions=tuple(
            ReviewedDimensionResponse(
                slug=item.slug,
                name=names.get(item.slug, (item.slug, Decimal(4)))[0],
                score=item.score,
                maximum=names.get(item.slug, (item.slug, Decimal(4)))[1],
                rationale=item.rationale,
                evidence=item.evidence,
            )
            for item in outcome.dimensions
        ),
        strengths=tuple(
            ReviewFindingResponse(statement=f.statement, instruction=f.instruction)
            for f in outcome.strengths
        ),
        corrections=tuple(
            ReviewFindingResponse(statement=f.statement, instruction=f.instruction)
            for f in outcome.corrections
        ),
        next_practice=outcome.next_practice,
        evidence_status=review.evidence_status,
        evidence_event_ids=tuple(int(i) for i in review.evidence_event_ids),
        created_at=review.created_at,
    )


__all__ = [
    "BLOCK_RUBRIC_SLUG",
    "REVIEW_JOB_KIND",
    "ReviewConflict",
    "ReviewInvalid",
    "ReviewNotFound",
    "ReviewService",
    "ReviewsError",
    "ReviewsUnavailable",
    "assign_dimensions",
    "build_evidence_command",
    "review_idempotency_key",
]
