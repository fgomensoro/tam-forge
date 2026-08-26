"""Transactional correction-slot reservation for the Today read model."""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from datetime import date

from sqlalchemy import Connection, func, insert, select, text
from sqlalchemy.orm import Session

from .models import Correction


class CorrectionSlotLimitError(ValueError):
    """Raised before persistence when a day already has its two correction slots."""


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
    "create_correction_with_slot_reservation",
]
