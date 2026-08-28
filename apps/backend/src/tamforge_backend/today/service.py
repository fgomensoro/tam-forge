"""Deterministic Today policy plus transactional correction-slot reservation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from datetime import date
from typing import Protocol

from sqlalchemy import Connection, func, insert, select, text
from sqlalchemy.orm import Session

from ..learning.time_policy import budget_for
from .models import Correction
from .schemas import (
    ContinueAction,
    DailyCloseCommand,
    DailyCloseResponse,
    TodayAnalysis,
    TodayBlock,
    TodayCorrection,
    TodayReadInput,
    TodayResponse,
    TodayTaskCard,
    TodayTimePolicy,
)


class CorrectionSlotLimitError(ValueError):
    """Raised before persistence when a day already has its two correction slots."""


class TodayError(Exception):
    """Base safe Today-workspace error."""


class TodayNotReady(TodayError):
    """The learner or active roadmap cannot produce the requested day."""


class TodayConflict(TodayError):
    """The requested close conflicts with durable day state."""


class TodayInvalidRequest(TodayError):
    """The Today request violates a bounded public contract."""


class TodayStore(Protocol):
    async def load_today(self, *, owner_id: int, local_date: date) -> TodayReadInput: ...

    async def close_day(
        self,
        *,
        owner_id: int,
        local_date: date,
        command: DailyCloseCommand,
        idempotency_key: str,
    ) -> DailyCloseResponse: ...


_COMPLETED_FOR_CLOSE = frozenset(
    {
        "self_review_complete",
        "ai_processing",
        "feedback_ready",
        "correction_due",
        "demonstrated",
        "needs_work",
        "incomplete",
        "superseded",
    }
)


def _ordered_tasks(tasks: tuple[TodayTaskCard, ...]) -> tuple[TodayTaskCard, ...]:
    return tuple(sorted(tasks, key=lambda item: (item.roadmap_order, item.activity_id)))


def select_primary_action(
    *,
    tasks: tuple[TodayTaskCard, ...],
    corrections: tuple[TodayCorrection, ...],
    analyses: tuple[TodayAnalysis, ...],
    day_status: str,
) -> ContinueAction | None:
    """Select exactly one action using the approved immutable priority order."""
    if day_status not in {"planned", "in_progress"}:
        return None
    ordered = _ordered_tasks(tasks)
    by_id = {item.activity_id: item for item in ordered}

    scheduled = sorted(
        (
            item
            for item in corrections
            if item.status == "scheduled"
            and item.attempt_b_activity_id is not None
            and item.attempt_b_activity_id in by_id
        ),
        key=lambda item: (item.due_date, item.priority, item.id),
    )
    if scheduled:
        correction = scheduled[0]
        assert correction.attempt_b_activity_id is not None
        target = by_id[correction.attempt_b_activity_id]
        return ContinueAction(
            kind="correction_warmup",
            target_id=target.activity_id,
            label="Complete today’s correction",
            allowed_ai_role=target.allowed_ai_role,
        )

    resumable = next(
        (item for item in ordered if item.state in {"active", "paused"}), None
    )
    if resumable is not None:
        return ContinueAction(
            kind="resume_activity",
            target_id=resumable.activity_id,
            label="Resume current activity",
            allowed_ai_role=resumable.allowed_ai_role,
        )

    pending_review = next(
        (item for item in ordered if item.state == "output_committed"), None
    )
    if pending_review is not None:
        return ContinueAction(
            kind="complete_self_review",
            target_id=pending_review.activity_id,
            label="Complete mandatory self-review",
            allowed_ai_role="none",
        )

    next_required = next(
        (
            item
            for item in ordered
            if item.required
            and item.state == "ready"
            and item.block not in {"correction_warmup", "daily_close"}
        ),
        None,
    )
    if next_required is not None:
        return ContinueAction(
            kind="start_activity",
            target_id=next_required.activity_id,
            label="Start next required activity",
            allowed_ai_role=next_required.allowed_ai_role,
        )

    ready_analysis = min(
        analyses,
        key=lambda item: (item.updated_at, item.activity_id),
        default=None,
    )
    if ready_analysis is not None:
        return ContinueAction(
            kind="review_feedback",
            target_id=ready_analysis.activity_id,
            label=(
                "Resolve processing issue"
                if ready_analysis.state == "needs_attention"
                else "Review ready feedback"
            ),
            allowed_ai_role="reviewer",
        )

    blockers = tuple(
        item
        for item in ordered
        if item.required
        and item.block != "daily_close"
        and item.state not in _COMPLETED_FOR_CLOSE
    )
    daily_close = next(
        (item for item in ordered if item.block == "daily_close"), None
    )
    if not blockers and daily_close is not None:
        return ContinueAction(
            kind="close_day",
            target_id=daily_close.activity_id,
            label="Close study day",
            allowed_ai_role=daily_close.allowed_ai_role,
        )
    return None


def _required_blocks(tasks: tuple[TodayTaskCard, ...]) -> tuple[TodayBlock, ...]:
    ordered_names: list[str] = []
    grouped: dict[str, list[TodayTaskCard]] = {}
    for task in _ordered_tasks(tasks):
        if not task.required:
            continue
        if task.block not in grouped:
            ordered_names.append(task.block)
            grouped[task.block] = []
        grouped[task.block].append(task)
    return tuple(
        TodayBlock(
            name=name,
            planned_minutes=sum(item.timebox_minutes for item in grouped[name]),
            activity_ids=tuple(item.activity_id for item in grouped[name]),
        )
        for name in ordered_names
    )


def build_today_response(source: TodayReadInput) -> TodayResponse:
    """Apply time, Sunday, Continue, and stable-version policy to one snapshot."""
    budget = budget_for(source.local_date)
    if source.planned_minutes > budget.maximum_minutes:
        raise TodayInvalidRequest("Today plan exceeds the protected time limit")
    if (
        source.day_type == "weekday"
        and source.planned_minutes < budget.acceptable_minimum
    ):
        raise TodayInvalidRequest("weekday plan is below the protected minimum")
    is_off = source.day_status == "off" or source.day_type == "sunday"
    tasks = () if is_off else _ordered_tasks(source.tasks)
    corrections = () if is_off else tuple(
        sorted(
            source.corrections,
            key=lambda item: (item.due_date, item.priority, item.id),
        )[:2]
    )
    analyses = tuple(
        sorted(source.analyses, key=lambda item: (item.updated_at, item.activity_id))
    )
    primary = (
        None
        if is_off
        else select_primary_action(
            tasks=tasks,
            corrections=corrections,
            analyses=analyses,
            day_status=source.day_status,
        )
    )
    time_policy = TodayTimePolicy(
        target_minutes=budget.target_minutes,
        acceptable_minimum=budget.acceptable_minimum,
        hard_stop_minutes=budget.maximum_minutes,
        focused_minutes=0 if is_off else source.focused_minutes,
        hard_stop_recommended=(
            not is_off
            and budget.maximum_minutes > 0
            and source.focused_minutes >= budget.maximum_minutes
        ),
    )
    version_payload = {
        "local_date": source.local_date.isoformat(),
        "day_id": source.day_id,
        "day_status": source.day_status,
        "roadmap": source.roadmap.model_dump(mode="json"),
        "planned_minutes": 0 if is_off else source.planned_minutes,
        "focused_minutes": 0 if is_off else source.focused_minutes,
        "tasks": [item.model_dump(mode="json") for item in tasks],
        "corrections": [item.model_dump(mode="json") for item in corrections],
        "interviews": [
            item.model_dump(mode="json")
            for item in sorted(source.interviews, key=lambda item: (item.starts_at, item.id))
        ],
        "self_reviews": [
            item.model_dump(mode="json")
            for item in sorted(
                source.awaiting_self_reviews,
                key=lambda item: (item.output_committed_at, item.activity_id),
            )
        ],
        "analyses": [item.model_dump(mode="json") for item in analyses],
        "source_updated_at": source.source_updated_at.isoformat(),
    }
    version = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return TodayResponse(
        local_date=source.local_date,
        timezone=source.timezone,
        day_id=None if is_off else source.day_id,
        day_type="sunday" if is_off else source.day_type,
        day_status="off" if is_off else source.day_status,
        roadmap=source.roadmap,
        total_planned_minutes=0 if is_off else source.planned_minutes,
        time_policy=time_policy,
        required_blocks=() if is_off else _required_blocks(tasks),
        tasks=tasks,
        corrections=corrections,
        interviews=tuple(
            sorted(source.interviews, key=lambda item: (item.starts_at, item.id))
        ),
        awaiting_self_reviews=tuple(
            sorted(
                source.awaiting_self_reviews,
                key=lambda item: (item.output_committed_at, item.activity_id),
            )
        ),
        analyses=analyses,
        primary_continue=primary,
        source_updated_at=source.source_updated_at,
        read_model_version=version,
        etag=f'"{version}"',
    )


class TodayService:
    def __init__(self, store: TodayStore) -> None:
        self._store = store

    async def get_today(self, *, owner_id: int, local_date: date) -> TodayResponse:
        if owner_id <= 0:
            raise TodayInvalidRequest("owner is invalid")
        return build_today_response(
            await self._store.load_today(owner_id=owner_id, local_date=local_date)
        )

    async def close_day(
        self,
        *,
        owner_id: int,
        local_date: date,
        command: DailyCloseCommand,
        idempotency_key: str,
    ) -> DailyCloseResponse:
        if owner_id <= 0 or not idempotency_key or len(idempotency_key) > 128:
            raise TodayInvalidRequest("daily-close identity is invalid")
        return await self._store.close_day(
            owner_id=owner_id,
            local_date=local_date,
            command=command,
            idempotency_key=idempotency_key,
        )


def _ensure_slot_available(
    active_priorities: Collection[int],
    *,
    candidate_priority: int,
) -> None:
    """Enforce two distinct active priority slots for one owner-local day.

    The caller obtains the owner/day lock and supplies only active rows. The
    database index supports that query but intentionally does not impose a
    global cardinality constraint on historical correction rows.
    """
    if candidate_priority not in {1, 2}:
        raise CorrectionSlotLimitError("correction priority slot must be 1 or 2")
    if len(active_priorities) >= 2:
        raise CorrectionSlotLimitError("a day cannot have more than two active corrections")
    if candidate_priority in active_priorities:
        raise CorrectionSlotLimitError("correction priority slot is already occupied")


def _correction_slot_lock_key(owner_id: int, due_date: date) -> int:
    material = f"{owner_id}:{due_date.isoformat()}".encode()
    digest = hashlib.blake2b(
        material,
        digest_size=8,
        person=b"tamforge-cslot",
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def create_correction_with_slot_reservation(
    database: Connection | Session,
    *,
    owner_id: int,
    source_activity_id: int,
    source_evidence_event_id: int,
    priority: int,
    due_date: date,
    instruction: str,
) -> int:
    """Serialize, validate, and insert one active correction in the caller transaction.

    PostgreSQL transaction-scoped advisory locking makes concurrent calls for
    the same owner-local date wait on one another. The lock, indexed read, and
    insert are deliberately one operation so a caller cannot reserve a slot
    without persisting it in that transaction.
    """
    if any(value <= 0 for value in (owner_id, source_activity_id, source_evidence_event_id)):
        raise CorrectionSlotLimitError("correction references must be positive IDs")
    if not instruction.strip() or len(instruction.encode()) > 1024:
        raise CorrectionSlotLimitError("correction instruction must be compact")

    database.execute(
        text("SELECT pg_advisory_xact_lock(:slot_lock_key)"),
        {"slot_lock_key": _correction_slot_lock_key(owner_id, due_date)},
    )
    active_rows = database.execute(
        select(Correction.priority).where(
            Correction.owner_id == owner_id,
            Correction.due_date == due_date,
            Correction.status.in_(("pending", "scheduled")),
        )
    ).all()
    active_priorities = [int(row[0]) for row in active_rows]
    _ensure_slot_available(active_priorities, candidate_priority=priority)

    result = database.execute(
        insert(Correction)
        .values(
            owner_id=owner_id,
            source_activity_id=source_activity_id,
            source_evidence_event_id=source_evidence_event_id,
            priority=priority,
            status="pending",
            due_date=due_date,
            instruction=instruction,
            attempt_b_activity_id=None,
            created_at=func.current_timestamp(),
            updated_at=func.current_timestamp(),
            completed_at=None,
        )
        .returning(Correction.id)
    )
    return int(result.scalar_one())


__all__ = [
    "CorrectionSlotLimitError",
    "TodayConflict",
    "TodayError",
    "TodayInvalidRequest",
    "TodayNotReady",
    "TodayService",
    "TodayStore",
    "build_today_response",
    "create_correction_with_slot_reservation",
    "select_primary_action",
]
