"""Transactional activity commands with durable idempotency and focused timers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.models import CommandReceipt, Owner
from ..database import transaction_scope
from ..models.base import utc_now
from .enums import ActivityState, IncompleteClassification
from .models import ActivityInstance, ActivityTimerSession, StudyDay
from .schemas import ActivityResponse, TimerResponse
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


@dataclass(frozen=True, slots=True)
class _LockedActivity:
    activity: ActivityInstance
    day: StudyDay


class ActivityService:
    """Execute one idempotent command per short owner-scoped transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._clock = clock

    async def get_activity(self, *, owner_id: int, activity_id: int) -> ActivityResponse:
        row = await self._load(owner_id=owner_id, activity_id=activity_id, lock=False)
        result = await self._response(row)
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

    async def _load(self, *, owner_id: int, activity_id: int, lock: bool) -> _LockedActivity:
        statement = (
            select(ActivityInstance, StudyDay)
            .join(
                StudyDay,
                (StudyDay.owner_id == ActivityInstance.owner_id)
                & (StudyDay.id == ActivityInstance.study_day_id),
            )
            .where(ActivityInstance.owner_id == owner_id)
            .where(ActivityInstance.id == activity_id)
        )
        if lock:
            statement = statement.with_for_update(of=(ActivityInstance, StudyDay))
        result = (await self._session.execute(statement)).first()
        if result is None:
            raise ActivityNotFound("activity was not found")
        return _LockedActivity(result[0], result[1])

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

    async def _duplicate(
        self,
        owner_id: int,
        scope: str,
        idempotency_key: str,
        request_hash: bytes,
    ) -> ActivityResponse | None:
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
        return ActivityResponse.model_validate(receipt.result_payload)

    async def _save_receipt(
        self,
        owner_id: int,
        scope: str,
        idempotency_key: str,
        request_hash: bytes,
        result: ActivityResponse,
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
        owner_lock = await self._session.scalar(
            select(Owner.id).where(Owner.id == owner_id).with_for_update()
        )
        if owner_lock is None:
            raise ActivityNotFound("activity owner was not found")
        existing = await self._session.scalar(
            select(ActivityTimerSession.id)
            .where(ActivityTimerSession.owner_id == owner_id)
            .where(ActivityTimerSession.idempotency_key == idempotency_key)
        )
        if existing is not None:
            raise ActivityConflict("Idempotency-Key was already used for a timer")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ActivityInvalidRequest("server clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _request_hash(*values: object) -> bytes:
        payload = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
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
