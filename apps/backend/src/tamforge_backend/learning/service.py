"""Transactional activity commands with durable idempotency and focused timers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.models import CommandReceipt, Owner
from ..database import transaction_scope
from ..models.base import utc_now
from ..roadmaps.models import TaskDefinition
from ..storage.models import ObjectStoreError, PresignPutRequest
from ..storage.ports import ObjectStore
from .artifacts import (
    ArtifactCommitment,
    ArtifactUploadIntent,
    ArtifactValidationError,
    build_commitment_digest,
    build_upload_intent,
    unencrypted_metadata,
    verify_confirm_request,
    verify_stored_object,
)
from .contracts import (
    ContractContext,
    OutputContractError,
    ValidatedOutput,
    validate_output_contract,
)
from .enums import ActivityState, IncompleteClassification
from .models import (
    ActivityArtifactLink,
    ActivityInstance,
    ActivityTimerSession,
    Artifact,
    Attempt,
    SelfReview,
    StudyDay,
)
from .schemas import (
    ActivityDetailResponse,
    ActivityResponse,
    ArtifactPresignResponse,
    ArtifactReference,
    ArtifactResponse,
    CommittedOutputSummary,
    OutputCommitResponse,
    PresignedUploadResponse,
    SelfReviewResponse,
    SelfReviewSummary,
    TimerResponse,
)
from .state_machine import ActivityStateError, TransitionDecision, transition
from .timers import TimerPolicyError, TimerState, apply_heartbeat, start_timer

_SAFE_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ActivityCommandError(Exception):
    """Base activity error safe to convert to a closed public problem response."""


class ActivityNotFound(ActivityCommandError):
    """The owner-scoped activity does not exist."""


class ActivityConflict(ActivityCommandError):
    """The activity state, timer, or optimistic version conflicts."""


class ActivityInvalidRequest(ActivityCommandError):
    """The command metadata violates a bounded public contract."""


class ActivityUnavailable(ActivityCommandError):
    """A required private service is temporarily unavailable."""


@dataclass(frozen=True, slots=True)
class _LockedActivity:
    activity: ActivityInstance
    day: StudyDay
    definition: TaskDefinition


class _ArtifactIntentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: int | None = None
    owner_id: int
    activity_id: int
    expected_version: int
    artifact_class: str
    object_key: str
    sha256: str
    byte_length: int
    content_type: str
    original_filename: str
    reused: bool


_ResponseT = TypeVar("_ResponseT", bound=BaseModel)


class ActivityService:
    """Execute one idempotent command per short owner-scoped transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
        object_store: ObjectStore | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._object_store = object_store

    async def get_activity(self, *, owner_id: int, activity_id: int) -> ActivityDetailResponse:
        row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=False)
        result = await self._detail_response(row)
        await self._session.rollback()
        return result

    async def start(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        idempotency_key: str,
    ) -> ActivityResponse:
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash("start", activity_id, expected_version)
            duplicate = await self._duplicate(
                owner_id, "activity.start", idempotency_key, request_hash
            )
            if duplicate is not None:
                return duplicate
            await self._assert_timer_key_available(owner_id, idempotency_key)
            decision = self._transition(
                row, ActivityState.ACTIVE, expected_version=expected_version
            )
            now = self._now()
            if row.day.status == "planned":
                row.day.status = "in_progress"
                row.day.started_at = now
            row.activity.state = decision.state.value
            row.activity.started_at = now
            row.activity.optimistic_version = decision.next_version
            initial = start_timer(now)
            timer = ActivityTimerSession(
                owner_id=owner_id,
                activity_instance_id=activity_id,
                idempotency_key=idempotency_key,
                started_at=initial.started_at,
                last_heartbeat_at=initial.last_heartbeat_at,
                paused_at=None,
                ended_at=None,
                counted_seconds=0,
                last_client_sequence=0,
            )
            self._session.add(timer)
            await self._session.flush()
            result = await self._response(row)
            await self._save_receipt(
                owner_id, "activity.start", idempotency_key, request_hash, result
            )
            return result

    async def heartbeat(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        client_sequence: int,
        idempotency_key: str,
    ) -> ActivityResponse:
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash(
                "heartbeat", activity_id, expected_version, client_sequence
            )
            duplicate = await self._duplicate(
                owner_id, "activity.heartbeat", idempotency_key, request_hash
            )
            if duplicate is not None:
                return duplicate
            if row.activity.optimistic_version != expected_version:
                raise ActivityConflict("stale activity version")
            if row.activity.state != ActivityState.ACTIVE.value:
                raise ActivityConflict("activity is not active")
            timer = await self._open_timer(row.activity, lock=True)
            if timer is None:
                raise ActivityConflict("active activity has no open timer")
            await self._apply_timer_heartbeat(
                row=row,
                timer=timer,
                client_sequence=client_sequence,
                server_now=self._now(),
            )
            result = await self._response(row)
            await self._save_receipt(
                owner_id, "activity.heartbeat", idempotency_key, request_hash, result
            )
            return result

    async def pause(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        client_sequence: int,
        idempotency_key: str,
    ) -> ActivityResponse:
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash(
                "pause", activity_id, expected_version, client_sequence
            )
            duplicate = await self._duplicate(
                owner_id, "activity.pause", idempotency_key, request_hash
            )
            if duplicate is not None:
                return duplicate
            decision = self._transition(
                row, ActivityState.PAUSED, expected_version=expected_version
            )
            timer = await self._open_timer(row.activity, lock=True)
            if timer is None:
                raise ActivityConflict("active activity has no open timer")
            now = self._now()
            await self._apply_timer_heartbeat(
                row=row,
                timer=timer,
                client_sequence=client_sequence,
                server_now=now,
            )
            timer.paused_at = now
            timer.ended_at = now
            row.activity.state = decision.state.value
            row.activity.optimistic_version = decision.next_version
            await self._session.flush()
            result = await self._response(row)
            await self._save_receipt(
                owner_id, "activity.pause", idempotency_key, request_hash, result
            )
            return result

    async def resume(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        idempotency_key: str,
    ) -> ActivityResponse:
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash("resume", activity_id, expected_version)
            duplicate = await self._duplicate(
                owner_id, "activity.resume", idempotency_key, request_hash
            )
            if duplicate is not None:
                return duplicate
            await self._assert_timer_key_available(owner_id, idempotency_key)
            decision = self._transition(
                row, ActivityState.ACTIVE, expected_version=expected_version
            )
            if await self._open_timer(row.activity, lock=True) is not None:
                raise ActivityConflict("paused activity already has an open timer")
            now = self._now()
            initial = start_timer(now)
            self._session.add(
                ActivityTimerSession(
                    owner_id=owner_id,
                    activity_instance_id=activity_id,
                    idempotency_key=idempotency_key,
                    started_at=initial.started_at,
                    last_heartbeat_at=initial.last_heartbeat_at,
                    paused_at=None,
                    ended_at=None,
                    counted_seconds=0,
                    last_client_sequence=0,
                )
            )
            row.activity.state = decision.state.value
            row.activity.optimistic_version = decision.next_version
            await self._session.flush()
            result = await self._response(row)
            await self._save_receipt(
                owner_id, "activity.resume", idempotency_key, request_hash, result
            )
            return result

    async def classify_incomplete(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        classification: IncompleteClassification,
        stronger_evidence_id: int | None,
        idempotency_key: str,
    ) -> ActivityResponse:
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash(
                "classify-incomplete",
                activity_id,
                expected_version,
                classification.value,
                stronger_evidence_id,
            )
            duplicate = await self._duplicate(
                owner_id,
                "activity.classify-incomplete",
                idempotency_key,
                request_hash,
            )
            if duplicate is not None:
                return duplicate
            await self._validate_incomplete_evidence(
                owner_id=owner_id,
                activity_id=activity_id,
                classification=classification,
                stronger_evidence_id=stronger_evidence_id,
            )
            decision = self._transition(
                row, ActivityState.INCOMPLETE, expected_version=expected_version
            )
            timer = await self._open_timer(row.activity, lock=True)
            now = self._now()
            if timer is not None:
                await self._apply_timer_heartbeat(
                    row=row,
                    timer=timer,
                    client_sequence=timer.last_client_sequence + 1,
                    server_now=now,
                )
                timer.ended_at = now
            row.activity.classification = classification.value
            row.activity.stronger_evidence_activity_id = stronger_evidence_id
            row.activity.completed_at = now
            row.activity.state = decision.state.value
            row.activity.optimistic_version = decision.next_version
            await self._session.flush()
            result = await self._response(row)
            await self._save_receipt(
                owner_id,
                "activity.classify-incomplete",
                idempotency_key,
                request_hash,
                result,
            )
            return result

    async def presign_artifact(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        artifact_class: str,
        sha256: str,
        byte_length: int,
        content_type: str,
        original_filename: str,
        idempotency_key: str,
    ) -> ArtifactPresignResponse:
        store = self._require_object_store()
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash(
                "artifact-presign",
                activity_id,
                expected_version,
                artifact_class,
                sha256,
                byte_length,
                content_type,
                original_filename,
            )
            receipt = await self._duplicate_as(
                owner_id,
                "activity.artifact.presign",
                idempotency_key,
                request_hash,
                _ArtifactIntentReceipt,
            )
            if receipt is None:
                self._require_version_and_state(
                    row,
                    expected_version=expected_version,
                    allowed_states={ActivityState.ACTIVE, ActivityState.PAUSED},
                )
                try:
                    intent = build_upload_intent(
                        owner_id=owner_id,
                        activity_id=activity_id,
                        artifact_class=artifact_class,
                        sha256=sha256,
                        byte_length=byte_length,
                        content_type=content_type,
                        original_filename=original_filename,
                    )
                except ArtifactValidationError as exc:
                    raise ActivityInvalidRequest(str(exc)) from None
                existing = await self._artifact_by_hash(owner_id=owner_id, sha256=sha256)
                if existing is not None:
                    self._validate_reusable_artifact(existing, intent)
                    await self._verify_reusable_stored_object(
                        store=store,
                        owner_id=owner_id,
                        artifact=existing,
                    )
                    receipt = self._intent_receipt(
                        intent,
                        expected_version=expected_version,
                        artifact_id=existing.id,
                        reused=True,
                        object_key=existing.object_key,
                    )
                else:
                    receipt = self._intent_receipt(
                        intent,
                        expected_version=expected_version,
                        artifact_id=None,
                        reused=False,
                    )
                await self._save_receipt(
                    owner_id,
                    "activity.artifact.presign",
                    idempotency_key,
                    request_hash,
                    receipt,
                )
            if receipt.reused and receipt.artifact_id is not None:
                await self._ensure_pending_artifact_link(
                    owner_id=owner_id,
                    activity_id=activity_id,
                    artifact_id=receipt.artifact_id,
                )
            if not receipt.reused and row.activity.state not in {
                ActivityState.ACTIVE.value,
                ActivityState.PAUSED.value,
            }:
                raise ActivityConflict("upload URL cannot be refreshed after output commitment")
            return await self._presign_response(store=store, receipt=receipt)

    async def confirm_artifact(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        upload_idempotency_key: str,
        object_key: str,
        idempotency_key: str,
    ) -> ArtifactResponse:
        store = self._require_object_store()
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash(
                "artifact-confirm",
                activity_id,
                expected_version,
                upload_idempotency_key,
                object_key,
            )
            duplicate = await self._duplicate_as(
                owner_id,
                "activity.artifact.confirm",
                idempotency_key,
                request_hash,
                ArtifactResponse,
            )
            if duplicate is not None:
                return duplicate
            self._require_version_and_state(
                row,
                expected_version=expected_version,
                allowed_states={ActivityState.ACTIVE, ActivityState.PAUSED},
            )
            upload_receipt = await self._load_artifact_intent(
                owner_id=owner_id,
                idempotency_key=upload_idempotency_key,
            )
            if (
                upload_receipt.owner_id != owner_id
                or upload_receipt.activity_id != activity_id
                or upload_receipt.expected_version != expected_version
            ):
                raise ActivityInvalidRequest("upload intent does not belong to this activity state")
            if upload_receipt.reused:
                if upload_receipt.artifact_id is None:
                    raise ActivityInvalidRequest("reused upload intent is invalid")
                artifact = await self._artifact_by_id(
                    owner_id=owner_id,
                    artifact_id=upload_receipt.artifact_id,
                )
                if artifact is None:
                    raise ActivityConflict("reused artifact no longer exists")
                await self._verify_reusable_stored_object(
                    store=store,
                    owner_id=owner_id,
                    artifact=artifact,
                )
                await self._ensure_pending_artifact_link(
                    owner_id=owner_id,
                    activity_id=activity_id,
                    artifact_id=artifact.id,
                )
            else:
                intent = self._upload_intent(upload_receipt)
                try:
                    verify_confirm_request(intent, object_key=object_key)
                    stored = await store.stat(intent.object_key)
                    if stored is None:
                        raise ArtifactValidationError("uploaded object was not found")
                    verify_stored_object(intent, stored)
                except ArtifactValidationError as exc:
                    raise ActivityInvalidRequest(str(exc)) from None
                except ObjectStoreError as exc:
                    raise ActivityUnavailable("private object storage is unavailable") from exc

                await self._lock_owner(owner_id)
                existing = await self._artifact_by_hash(owner_id=owner_id, sha256=intent.sha256)
                if existing is not None:
                    self._validate_reusable_artifact(existing, intent)
                    artifact = existing
                else:
                    artifact = Artifact(
                        owner_id=owner_id,
                        object_key=intent.object_key,
                        content_hash=bytes.fromhex(intent.sha256),
                        content_type=intent.content_type,
                        original_filename=intent.original_filename,
                        byte_size=intent.byte_length,
                        artifact_class=intent.artifact_class,
                        encryption_metadata=unencrypted_metadata(),
                        derived_from_artifact_id=None,
                        immutable_version=1,
                        created_at=self._now(),
                    )
                    self._session.add(artifact)
                    await self._session.flush()
                await self._ensure_pending_artifact_link(
                    owner_id=owner_id,
                    activity_id=activity_id,
                    artifact_id=artifact.id,
                )
            result = self._artifact_response(artifact)
            await self._save_receipt(
                owner_id,
                "activity.artifact.confirm",
                idempotency_key,
                request_hash,
                result,
            )
            return result

    async def set_source_visibility(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        hidden: bool,
        idempotency_key: str,
    ) -> ActivityDetailResponse:
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash(
                "source-visibility", activity_id, expected_version, hidden
            )
            duplicate = await self._duplicate_as(
                owner_id,
                "activity.source-visibility",
                idempotency_key,
                request_hash,
                ActivityDetailResponse,
            )
            if duplicate is not None:
                return duplicate
            self._require_version_and_state(
                row,
                expected_version=expected_version,
                allowed_states={ActivityState.READY, ActivityState.ACTIVE, ActivityState.PAUSED},
            )
            if row.activity.source_hidden != hidden:
                row.activity.source_hidden = hidden
                row.activity.optimistic_version += 1
                await self._session.flush()
            result = await self._detail_response(row)
            await self._save_receipt(
                owner_id,
                "activity.source-visibility",
                idempotency_key,
                request_hash,
                result,
            )
            return result

    async def commit_output(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        client_sequence: int,
        output: dict[str, object],
        artifact_refs: tuple[ArtifactReference, ...],
        parent_attempt_id: int | None,
        idempotency_key: str,
    ) -> OutputCommitResponse:
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash(
                "commit-output",
                activity_id,
                expected_version,
                client_sequence,
                output,
                [item.model_dump(mode="json") for item in artifact_refs],
                parent_attempt_id,
            )
            duplicate = await self._duplicate_as(
                owner_id,
                "activity.commit-output",
                idempotency_key,
                request_hash,
                OutputCommitResponse,
            )
            if duplicate is not None:
                return duplicate
            decision = self._transition(
                row, ActivityState.OUTPUT_COMMITTED, expected_version=expected_version
            )
            validated = await self._validate_output(
                row,
                output,
                owner_id=owner_id,
                parent_attempt_id=parent_attempt_id,
            )
            attempt_kind = await self._select_attempt_kind(
                row=row,
                owner_id=owner_id,
                parent_attempt_id=parent_attempt_id,
                prompt=validated.prompt,
            )
            commitments, artifacts = await self._load_commitment_artifacts(
                owner_id=owner_id,
                activity_id=activity_id,
                refs=artifact_refs,
            )
            try:
                commitment_hash = build_commitment_digest(validated, commitments)
            except ArtifactValidationError as exc:
                raise ActivityInvalidRequest(str(exc)) from None

            timer = await self._open_timer(row.activity, lock=True)
            if timer is None:
                raise ActivityConflict("active activity has no open timer")
            now = self._now()
            await self._apply_timer_heartbeat(
                row=row,
                timer=timer,
                client_sequence=client_sequence,
                server_now=now,
            )
            timer.ended_at = now
            row.activity.attempt_kind = attempt_kind
            row.activity.state = decision.state.value
            row.activity.output_committed_at = now
            row.activity.optimistic_version = decision.next_version
            await self._session.flush()

            attempt = Attempt(
                owner_id=owner_id,
                activity_instance_id=activity_id,
                attempt_kind=attempt_kind,
                parent_attempt_id=parent_attempt_id,
                original_text=validated.canonical_json,
                original_markdown=validated.original_markdown,
                original_sql=validated.original_sql,
                audience=validated.audience,
                prompt=validated.prompt,
                assistance_mode=row.activity.assistance_mode,
                commitment_hash=commitment_hash,
                committed_at=now,
                created_at=now,
            )
            self._session.add(attempt)
            await self._session.flush()
            for reference, artifact in artifacts:
                self._session.add(
                    ActivityArtifactLink(
                        owner_id=owner_id,
                        activity_instance_id=activity_id,
                        attempt_id=attempt.id,
                        artifact_id=artifact.id,
                        link_role=reference.link_role,
                        created_at=now,
                    )
                )
            await self._session.flush()
            result = OutputCommitResponse(
                activity_id=activity_id,
                state=ActivityState.OUTPUT_COMMITTED,
                optimistic_version=row.activity.optimistic_version,
                attempt_id=attempt.id,
                commitment_sha256=commitment_hash.hex(),
                artifact_ids=tuple(sorted(artifact.id for _, artifact in artifacts)),
            )
            await self._save_receipt(
                owner_id,
                "activity.commit-output",
                idempotency_key,
                request_hash,
                result,
            )
            return result

    async def submit_self_review(
        self,
        *,
        owner_id: int,
        activity_id: int,
        expected_version: int,
        main_answer: str,
        did_well: str,
        structure_weakness: str,
        vague_points: str,
        hesitation_points: str,
        change_next: str,
        self_score: int,
        idempotency_key: str,
    ) -> SelfReviewResponse:
        self._validate_self_review_values(
            main_answer,
            did_well,
            structure_weakness,
            vague_points,
            hesitation_points,
            change_next,
            self_score,
        )
        async with transaction_scope(self._session):
            row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=True)
            request_hash = self._request_hash(
                "self-review",
                activity_id,
                expected_version,
                main_answer,
                did_well,
                structure_weakness,
                vague_points,
                hesitation_points,
                change_next,
                self_score,
            )
            duplicate = await self._duplicate_as(
                owner_id,
                "activity.self-review",
                idempotency_key,
                request_hash,
                SelfReviewResponse,
            )
            if duplicate is not None:
                return duplicate
            decision = self._transition(
                row, ActivityState.SELF_REVIEW_COMPLETE, expected_version=expected_version
            )
            attempt = await self._attempt_for_activity(
                owner_id=owner_id,
                activity_id=activity_id,
                lock=True,
            )
            if attempt is None:
                raise ActivityConflict("committed activity has no immutable attempt")
            now = self._now()
            review = SelfReview(
                owner_id=owner_id,
                activity_instance_id=activity_id,
                attempt_id=attempt.id,
                main_answer=main_answer,
                did_well=did_well,
                structure_weakness=structure_weakness,
                vague_points=vague_points,
                hesitation_points=hesitation_points,
                change_next=change_next,
                self_score=self_score,
                submitted_at=now,
            )
            self._session.add(review)
            row.activity.state = decision.state.value
            row.activity.optimistic_version = decision.next_version
            await self._session.flush()
            result = SelfReviewResponse(
                activity_id=activity_id,
                state=ActivityState.SELF_REVIEW_COMPLETE,
                optimistic_version=row.activity.optimistic_version,
                self_review_id=review.id,
                attempt_id=attempt.id,
                self_score=self_score,
            )
            await self._save_receipt(
                owner_id,
                "activity.self-review",
                idempotency_key,
                request_hash,
                result,
            )
            return result

    async def _load(self, *, owner_id: int, activity_id: int, lock: bool) -> _LockedActivity:
        statement = (
            select(ActivityInstance, StudyDay, TaskDefinition)
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
            .where(ActivityInstance.owner_id == owner_id)
            .where(ActivityInstance.id == activity_id)
        )
        if lock:
            statement = statement.with_for_update(of=(ActivityInstance, StudyDay))
        result = (await self._session.execute(statement)).first()
        if result is None:
            raise ActivityNotFound("activity was not found")
        return _LockedActivity(result[0], result[1], result[2])

    def _transition(
        self,
        row: _LockedActivity,
        target: ActivityState,
        *,
        expected_version: int,
    ) -> TransitionDecision:
        try:
            return transition(
                current=ActivityState(row.activity.state),
                target=target,
                actual_version=row.activity.optimistic_version,
                expected_version=expected_version,
                day_type=row.day.day_type,
                day_status=row.day.status,
            )
        except (ActivityStateError, ValueError) as exc:
            raise ActivityConflict(str(exc)) from None

    async def _open_timer(
        self, activity: ActivityInstance, *, lock: bool
    ) -> ActivityTimerSession | None:
        statement = (
            select(ActivityTimerSession)
            .where(ActivityTimerSession.owner_id == activity.owner_id)
            .where(ActivityTimerSession.activity_instance_id == activity.id)
            .where(ActivityTimerSession.ended_at.is_(None))
        )
        if lock:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _day_seconds(self, row: _LockedActivity) -> int:
        value = await self._session.scalar(
            select(func.coalesce(func.sum(ActivityTimerSession.counted_seconds), 0))
            .join(
                ActivityInstance,
                (ActivityInstance.owner_id == ActivityTimerSession.owner_id)
                & (ActivityInstance.id == ActivityTimerSession.activity_instance_id),
            )
            .where(ActivityInstance.owner_id == row.activity.owner_id)
            .where(ActivityInstance.study_day_id == row.day.id)
        )
        return int(value or 0)

    async def _activity_seconds(self, activity: ActivityInstance) -> int:
        value = await self._session.scalar(
            select(func.coalesce(func.sum(ActivityTimerSession.counted_seconds), 0))
            .where(ActivityTimerSession.owner_id == activity.owner_id)
            .where(ActivityTimerSession.activity_instance_id == activity.id)
        )
        return int(value or 0)

    async def _apply_timer_heartbeat(
        self,
        *,
        row: _LockedActivity,
        timer: ActivityTimerSession,
        client_sequence: int,
        server_now: datetime,
    ) -> None:
        day_seconds = await self._day_seconds(row)
        maximum_seconds = (120 if row.day.day_type == "saturday" else 255) * 60
        try:
            decision = apply_heartbeat(
                TimerState(
                    started_at=timer.started_at,
                    last_heartbeat_at=timer.last_heartbeat_at,
                    counted_seconds=timer.counted_seconds,
                    last_client_sequence=timer.last_client_sequence,
                    paused_at=timer.paused_at,
                    ended_at=timer.ended_at,
                ),
                server_now=server_now,
                client_sequence=client_sequence,
                day_counted_seconds=day_seconds,
                day_hard_stop_seconds=maximum_seconds,
            )
        except TimerPolicyError as exc:
            raise ActivityConflict(str(exc)) from None
        timer.last_heartbeat_at = decision.timer.last_heartbeat_at
        timer.counted_seconds = decision.timer.counted_seconds
        timer.last_client_sequence = decision.timer.last_client_sequence
        await self._session.flush()
        row.day.focused_minutes = min(maximum_seconds // 60, decision.day_counted_seconds // 60)

    async def _response(self, row: _LockedActivity) -> ActivityResponse:
        timer = await self._open_timer(row.activity, lock=False)
        activity_seconds = await self._activity_seconds(row.activity)
        maximum_minutes = 120 if row.day.day_type == "saturday" else 255
        return ActivityResponse(
            id=row.activity.id,
            study_day_id=row.day.id,
            state=ActivityState(row.activity.state),
            optimistic_version=row.activity.optimistic_version,
            classification=IncompleteClassification(row.activity.classification),
            stronger_evidence_id=row.activity.stronger_evidence_activity_id,
            activity_focused_seconds=activity_seconds,
            day_focused_minutes=row.day.focused_minutes,
            hard_stop_recommended=row.day.focused_minutes >= maximum_minutes,
            source_hidden=row.activity.source_hidden,
            open_timer=(
                None
                if timer is None
                else TimerResponse(
                    id=timer.id,
                    started_at=timer.started_at,
                    last_heartbeat_at=timer.last_heartbeat_at,
                    counted_seconds=timer.counted_seconds,
                    last_client_sequence=timer.last_client_sequence,
                )
            ),
        )

    async def _detail_response(self, row: _LockedActivity) -> ActivityDetailResponse:
        base = await self._response(row)
        attempt = await self._attempt_for_activity(
            owner_id=row.activity.owner_id,
            activity_id=row.activity.id,
            lock=False,
        )
        committed: CommittedOutputSummary | None = None
        review_summary: SelfReviewSummary | None = None
        if attempt is not None:
            try:
                contract_payload = json.loads(attempt.original_text or "")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ActivityConflict("committed output snapshot is invalid") from exc
            if not isinstance(contract_payload, dict):
                raise ActivityConflict("committed output snapshot is invalid")
            artifact_ids = tuple(
                (
                    await self._session.execute(
                        select(ActivityArtifactLink.artifact_id)
                        .where(ActivityArtifactLink.owner_id == row.activity.owner_id)
                        .where(ActivityArtifactLink.activity_instance_id == row.activity.id)
                        .where(ActivityArtifactLink.attempt_id == attempt.id)
                        .order_by(ActivityArtifactLink.artifact_id)
                    )
                ).scalars()
            )
            committed = CommittedOutputSummary(
                attempt_id=attempt.id,
                attempt_kind=attempt.attempt_kind,
                commitment_sha256=attempt.commitment_hash.hex(),
                contract_payload=contract_payload,
                artifact_ids=artifact_ids,
                committed_at=attempt.committed_at,
            )
            review = (
                await self._session.execute(
                    select(SelfReview)
                    .where(SelfReview.owner_id == row.activity.owner_id)
                    .where(SelfReview.activity_instance_id == row.activity.id)
                    .where(SelfReview.attempt_id == attempt.id)
                )
            ).scalar_one_or_none()
            if review is not None:
                review_summary = SelfReviewSummary(
                    id=review.id,
                    attempt_id=review.attempt_id,
                    self_score=review.self_score,
                    main_answer=review.main_answer,
                    did_well=review.did_well,
                    structure_weakness=review.structure_weakness,
                    vague_points=review.vague_points,
                    hesitation_points=review.hesitation_points,
                    change_next=review.change_next,
                    submitted_at=review.submitted_at,
                )
        return ActivityDetailResponse(
            **base.model_dump(),
            committed_output=committed,
            self_review=review_summary,
        )

    async def _duplicate(
        self,
        owner_id: int,
        scope: str,
        idempotency_key: str,
        request_hash: bytes,
    ) -> ActivityResponse | None:
        return await self._duplicate_as(
            owner_id,
            scope,
            idempotency_key,
            request_hash,
            ActivityResponse,
        )

    async def _duplicate_as(
        self,
        owner_id: int,
        scope: str,
        idempotency_key: str,
        request_hash: bytes,
        response_type: type[_ResponseT],
    ) -> _ResponseT | None:
        self._validate_idempotency(idempotency_key)
        receipt = (
            await self._session.execute(
                select(CommandReceipt)
                .where(CommandReceipt.owner_id == owner_id)
                .where(CommandReceipt.command_scope == scope)
                .where(CommandReceipt.idempotency_key == idempotency_key)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if receipt is None:
            return None
        if receipt.request_hash != request_hash:
            raise ActivityConflict("Idempotency-Key was reused for another command")
        return response_type.model_validate(receipt.result_payload)

    async def _save_receipt(
        self,
        owner_id: int,
        scope: str,
        idempotency_key: str,
        request_hash: bytes,
        result: BaseModel,
    ) -> None:
        now = self._now()
        self._session.add(
            CommandReceipt(
                owner_id=owner_id,
                command_scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                status="completed",
                result_payload=result.model_dump(mode="json"),
                created_at=now,
                expires_at=now + timedelta(days=7),
            )
        )
        await self._session.flush()

    async def _assert_timer_key_available(self, owner_id: int, idempotency_key: str) -> None:
        await self._lock_owner(owner_id)
        existing = await self._session.scalar(
            select(ActivityTimerSession.id)
            .where(ActivityTimerSession.owner_id == owner_id)
            .where(ActivityTimerSession.idempotency_key == idempotency_key)
        )
        if existing is not None:
            raise ActivityConflict("Idempotency-Key was already used for a timer")

    async def _lock_owner(self, owner_id: int) -> None:
        owner_lock = await self._session.scalar(
            select(Owner.id).where(Owner.id == owner_id).with_for_update()
        )
        if owner_lock is None:
            raise ActivityNotFound("activity owner was not found")

    def _require_object_store(self) -> ObjectStore:
        if self._object_store is None:
            raise ActivityUnavailable("private object storage is unavailable")
        return self._object_store

    @staticmethod
    def _require_version_and_state(
        row: _LockedActivity,
        *,
        expected_version: int,
        allowed_states: set[ActivityState],
    ) -> None:
        if row.activity.optimistic_version != expected_version:
            raise ActivityConflict("stale activity version")
        if ActivityState(row.activity.state) not in allowed_states:
            raise ActivityConflict("activity state does not allow this command")

    @staticmethod
    def _intent_receipt(
        intent: ArtifactUploadIntent,
        *,
        expected_version: int,
        artifact_id: int | None,
        reused: bool,
        object_key: str | None = None,
    ) -> _ArtifactIntentReceipt:
        return _ArtifactIntentReceipt(
            artifact_id=artifact_id,
            owner_id=intent.owner_id,
            activity_id=intent.activity_id,
            expected_version=expected_version,
            artifact_class=intent.artifact_class,
            object_key=object_key or intent.object_key,
            sha256=intent.sha256,
            byte_length=intent.byte_length,
            content_type=intent.content_type,
            original_filename=intent.original_filename,
            reused=reused,
        )

    @staticmethod
    def _upload_intent(receipt: _ArtifactIntentReceipt) -> ArtifactUploadIntent:
        try:
            return build_upload_intent(
                owner_id=receipt.owner_id,
                activity_id=receipt.activity_id,
                artifact_class=receipt.artifact_class,
                sha256=receipt.sha256,
                byte_length=receipt.byte_length,
                content_type=receipt.content_type,
                original_filename=receipt.original_filename,
            )
        except ArtifactValidationError as exc:
            raise ActivityInvalidRequest("stored upload intent is invalid") from exc

    async def _load_artifact_intent(
        self,
        *,
        owner_id: int,
        idempotency_key: str,
    ) -> _ArtifactIntentReceipt:
        self._validate_idempotency(idempotency_key)
        receipt = (
            await self._session.execute(
                select(CommandReceipt)
                .where(CommandReceipt.owner_id == owner_id)
                .where(CommandReceipt.command_scope == "activity.artifact.presign")
                .where(CommandReceipt.idempotency_key == idempotency_key)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if receipt is None or receipt.status != "completed" or receipt.expires_at <= self._now():
            raise ActivityInvalidRequest("upload intent was not found")
        try:
            return _ArtifactIntentReceipt.model_validate(receipt.result_payload)
        except ValueError as exc:
            raise ActivityInvalidRequest("stored upload intent is invalid") from exc

    async def _presign_response(
        self,
        *,
        store: ObjectStore,
        receipt: _ArtifactIntentReceipt,
    ) -> ArtifactPresignResponse:
        if receipt.reused:
            return ArtifactPresignResponse(
                artifact_id=receipt.artifact_id,
                object_key=receipt.object_key,
                reused=True,
                upload=None,
            )
        intent = self._upload_intent(receipt)
        try:
            signed = await store.presign_put(
                PresignPutRequest(
                    key=intent.object_key,
                    sha256=intent.sha256,
                    byte_length=intent.byte_length,
                    content_type=intent.content_type,
                    metadata=intent.metadata,
                    expires_seconds=300,
                )
            )
        except ObjectStoreError as exc:
            raise ActivityUnavailable("private object storage is unavailable") from exc
        return ArtifactPresignResponse(
            artifact_id=None,
            object_key=intent.object_key,
            reused=False,
            upload=PresignedUploadResponse(
                url=signed.url,
                method="PUT",
                headers=dict(signed.headers),
                expires_seconds=signed.expires_seconds,
            ),
        )

    async def _artifact_by_hash(self, *, owner_id: int, sha256: str) -> Artifact | None:
        try:
            content_hash = bytes.fromhex(sha256)
        except ValueError:
            return None
        return (
            await self._session.execute(
                select(Artifact)
                .where(Artifact.owner_id == owner_id)
                .where(Artifact.content_hash == content_hash)
                .with_for_update(read=True, key_share=True)
            )
        ).scalar_one_or_none()

    async def _artifact_by_id(self, *, owner_id: int, artifact_id: int) -> Artifact | None:
        return (
            await self._session.execute(
                select(Artifact)
                .where(Artifact.owner_id == owner_id)
                .where(Artifact.id == artifact_id)
                .with_for_update(read=True, key_share=True)
            )
        ).scalar_one_or_none()

    async def _ensure_pending_artifact_link(
        self,
        *,
        owner_id: int,
        activity_id: int,
        artifact_id: int,
    ) -> None:
        existing = await self._session.scalar(
            select(ActivityArtifactLink.id)
            .where(ActivityArtifactLink.owner_id == owner_id)
            .where(ActivityArtifactLink.activity_instance_id == activity_id)
            .where(ActivityArtifactLink.attempt_id.is_(None))
            .where(ActivityArtifactLink.artifact_id == artifact_id)
            .where(ActivityArtifactLink.link_role == "supporting")
        )
        if existing is not None:
            return
        self._session.add(
            ActivityArtifactLink(
                owner_id=owner_id,
                activity_instance_id=activity_id,
                attempt_id=None,
                artifact_id=artifact_id,
                link_role="supporting",
                created_at=self._now(),
            )
        )
        await self._session.flush()

    @staticmethod
    def _validate_reusable_artifact(
        artifact: Artifact,
        intent: ArtifactUploadIntent,
    ) -> None:
        if (
            artifact.content_hash.hex() != intent.sha256
            or artifact.byte_size != intent.byte_length
            or artifact.content_type != intent.content_type
            or artifact.artifact_class != intent.artifact_class
        ):
            raise ActivityConflict("existing content hash has incompatible artifact metadata")

    @staticmethod
    async def _verify_reusable_stored_object(
        *,
        store: ObjectStore,
        owner_id: int,
        artifact: Artifact,
    ) -> None:
        try:
            stored = await store.stat(artifact.object_key)
        except ObjectStoreError as exc:
            raise ActivityUnavailable("private object storage is unavailable") from exc
        if (
            stored is None
            or stored.sha256 != artifact.content_hash.hex()
            or stored.byte_length != artifact.byte_size
            or stored.content_type != artifact.content_type
            or stored.metadata.get("owner-id") != str(owner_id)
        ):
            raise ActivityConflict("stored artifact no longer matches immutable metadata")

    @staticmethod
    def _artifact_response(artifact: Artifact) -> ArtifactResponse:
        return ArtifactResponse(
            id=artifact.id,
            sha256=artifact.content_hash.hex(),
            byte_length=artifact.byte_size,
            content_type=artifact.content_type,
            original_filename=artifact.original_filename,
            artifact_class=artifact.artifact_class,
        )

    async def _validate_output(
        self,
        row: _LockedActivity,
        output: dict[str, object],
        *,
        owner_id: int,
        parent_attempt_id: int | None,
    ) -> ValidatedOutput:
        exercise_type = row.definition.exercise_type
        mapping_version = row.definition.mapping_version
        if row.definition.block == "correction_warmup":
            if parent_attempt_id is None:
                raise ActivityInvalidRequest("Attempt B requires its source Attempt A")
            parent = await self._session.scalar(
                select(Attempt)
                .where(Attempt.owner_id == owner_id)
                .where(Attempt.id == parent_attempt_id)
                .with_for_update(read=True, key_share=True)
            )
            if parent is None or parent.attempt_kind != "attempt_a":
                raise ActivityInvalidRequest("Attempt B parent must be an owner-scoped Attempt A")
            exercise_type, mapping_version = self._parent_evidence_mapping(parent)
        if exercise_type is None or mapping_version is None:
            raise ActivityConflict("task evidence mapping is incomplete")
        try:
            return validate_output_contract(
                output,
                context=ContractContext(
                    block=row.definition.block,
                    source_hidden=row.activity.source_hidden,
                    timebox_minutes=row.activity.timebox_minutes,
                    task_stable_id=row.activity.task_stable_id_snapshot,
                    exercise_type=exercise_type,
                    mapping_version=mapping_version,
                    roadmap_version_key=row.activity.roadmap_version_key_snapshot,
                    task_definition_id=row.activity.task_definition_id,
                ),
            )
        except OutputContractError as exc:
            raise ActivityInvalidRequest(str(exc)) from None

    @staticmethod
    def _parent_evidence_mapping(parent: Attempt) -> tuple[str, str]:
        try:
            payload = json.loads(parent.original_text or "")
            context = payload["task_context"]
            exercise_type = context["exercise_type"]
            mapping_version = context["mapping_version"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ActivityConflict("Attempt A evidence mapping is invalid") from exc
        if (
            not isinstance(exercise_type, str)
            or not exercise_type.strip()
            or not isinstance(mapping_version, str)
            or not mapping_version.strip()
        ):
            raise ActivityConflict("Attempt A evidence mapping is invalid")
        return exercise_type, mapping_version

    async def _select_attempt_kind(
        self,
        *,
        row: _LockedActivity,
        owner_id: int,
        parent_attempt_id: int | None,
        prompt: str,
    ) -> str:
        current = row.activity.attempt_kind
        if current == "none":
            if row.definition.block == "correction_warmup":
                if parent_attempt_id is None:
                    raise ActivityInvalidRequest("Attempt B requires its source Attempt A")
                current = "attempt_b"
            else:
                if parent_attempt_id is not None:
                    raise ActivityInvalidRequest("Attempt A cannot have a parent attempt")
                current = "attempt_a"
        if current == "attempt_b":
            if parent_attempt_id is None:
                raise ActivityInvalidRequest("Attempt B requires its source Attempt A")
            parent = await self._session.scalar(
                select(Attempt)
                .where(Attempt.owner_id == owner_id)
                .where(Attempt.id == parent_attempt_id)
                .with_for_update(read=True, key_share=True)
            )
            if parent is None or parent.attempt_kind != "attempt_a":
                raise ActivityInvalidRequest("Attempt B parent must be an owner-scoped Attempt A")
            if parent.prompt != prompt:
                raise ActivityInvalidRequest("Attempt B must use the same prompt as Attempt A")
        elif parent_attempt_id is not None:
            raise ActivityInvalidRequest("only Attempt B can have a parent attempt")
        return current

    async def _load_commitment_artifacts(
        self,
        *,
        owner_id: int,
        activity_id: int,
        refs: tuple[ArtifactReference, ...],
    ) -> tuple[tuple[ArtifactCommitment, ...], tuple[tuple[ArtifactReference, Artifact], ...]]:
        if len({(item.artifact_id, item.link_role) for item in refs}) != len(refs):
            raise ActivityInvalidRequest("artifact references contain duplicate links")
        if not refs:
            return (), ()
        artifact_ids = {item.artifact_id for item in refs}
        artifacts = tuple(
            (
                await self._session.execute(
                    select(Artifact)
                    .where(Artifact.owner_id == owner_id)
                    .where(Artifact.id.in_(artifact_ids))
                    .with_for_update(read=True, key_share=True)
                )
            ).scalars()
        )
        by_id = {item.id: item for item in artifacts}
        if set(by_id) != artifact_ids:
            raise ActivityInvalidRequest("artifact reference was not found for this owner")
        bound_ids = set(
            (
                await self._session.execute(
                    select(ActivityArtifactLink.artifact_id)
                    .where(ActivityArtifactLink.owner_id == owner_id)
                    .where(ActivityArtifactLink.activity_instance_id == activity_id)
                    .where(ActivityArtifactLink.attempt_id.is_(None))
                    .where(ActivityArtifactLink.artifact_id.in_(artifact_ids))
                )
            ).scalars()
        )
        if bound_ids != artifact_ids:
            raise ActivityInvalidRequest("artifact was not uploaded for this activity")
        paired = tuple((reference, by_id[reference.artifact_id]) for reference in refs)
        commitments = tuple(
            ArtifactCommitment(
                artifact_id=artifact.id,
                sha256=artifact.content_hash.hex(),
                link_role=reference.link_role,
            )
            for reference, artifact in paired
        )
        return commitments, paired

    @staticmethod
    def _validate_self_review_values(*values: object) -> None:
        *answers, self_score = values
        if (
            not isinstance(self_score, int)
            or isinstance(self_score, bool)
            or not 0 <= self_score <= 4
            or any(
                not isinstance(answer, str)
                or not answer.strip()
                or len(answer.encode("utf-8")) > 8192
                for answer in answers
            )
        ):
            raise ActivityInvalidRequest("self-review answers or score are invalid")

    async def _attempt_for_activity(
        self,
        *,
        owner_id: int,
        activity_id: int,
        lock: bool,
    ) -> Attempt | None:
        statement = (
            select(Attempt)
            .where(Attempt.owner_id == owner_id)
            .where(Attempt.activity_instance_id == activity_id)
        )
        if lock:
            statement = statement.with_for_update(read=True, key_share=True)
        return (await self._session.execute(statement)).scalar_one_or_none()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ActivityInvalidRequest("server clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _request_hash(*values: object) -> bytes:
        payload = json.dumps(
            values,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).digest()

    @staticmethod
    def _validate_idempotency(value: str) -> None:
        if not _SAFE_IDEMPOTENCY.fullmatch(value):
            raise ActivityInvalidRequest("Idempotency-Key is invalid")

    async def _validate_incomplete_evidence(
        self,
        *,
        owner_id: int,
        activity_id: int,
        classification: IncompleteClassification,
        stronger_evidence_id: int | None,
    ) -> None:
        is_superseded = classification is IncompleteClassification.SUPERSEDED
        if is_superseded != (stronger_evidence_id is not None):
            raise ActivityInvalidRequest(
                "superseded incomplete work requires exactly one stronger evidence ID"
            )
        if stronger_evidence_id is None:
            return
        if stronger_evidence_id == activity_id:
            raise ActivityInvalidRequest("activity cannot supersede itself")
        evidence = await self._session.scalar(
            select(ActivityInstance.id)
            .where(ActivityInstance.owner_id == owner_id)
            .where(ActivityInstance.id == stronger_evidence_id)
            .with_for_update(read=True, key_share=True)
        )
        if evidence is None:
            raise ActivityInvalidRequest("stronger evidence activity was not found")
