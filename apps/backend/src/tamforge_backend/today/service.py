"""Small deterministic policies used while constructing the Today read model."""

from __future__ import annotations

from collections.abc import Collection


class CorrectionSlotLimitError(ValueError):
    """Raised before persistence when a day already has its two correction slots."""


def ensure_slot_available(
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


__all__ = ["CorrectionSlotLimitError", "ensure_slot_available"]
