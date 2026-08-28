"""Versioned evidence trend calculation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from .config_models import TrendRules

TREND_QUANTUM = Decimal("0.001")


class TrendEvent(Protocol):
    @property
    def event_id(self) -> int | str: ...

    @property
    def performance_score(self) -> Decimal: ...

    @property
    def effective_weight(self) -> Decimal: ...

    @property
    def occurred_at(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class TrendResult:
    code: str
    delta: Decimal | None
    preceding_average: Decimal | None
    recent_average: Decimal | None
    event_ids: tuple[int | str, ...]


def _weighted_average(events: tuple[TrendEvent, ...]) -> Decimal | None:
    total_weight = sum((item.effective_weight for item in events), Decimal("0"))
    if total_weight <= 0:
        return None
    return sum(
        (item.performance_score * item.effective_weight for item in events),
        Decimal("0"),
    ) / total_weight


def calculate_trend(
    events: Sequence[TrendEvent], *, rules: TrendRules
) -> TrendResult:
    required = rules.recent_event_count + rules.preceding_event_count
    ordered = tuple(sorted(events, key=lambda item: (item.occurred_at, str(item.event_id))))
    if len(ordered) < required:
        return TrendResult("insufficient_evidence", None, None, None, ())
    selected = ordered[-required:]
    preceding = selected[: rules.preceding_event_count]
    recent = selected[rules.preceding_event_count :]
    preceding_average = _weighted_average(preceding)
    recent_average = _weighted_average(recent)
    event_ids = tuple(item.event_id for item in selected)
    if preceding_average is None or recent_average is None:
        return TrendResult("insufficient_evidence", None, None, None, event_ids)
    delta = (recent_average - preceding_average).quantize(
        TREND_QUANTUM, rounding=ROUND_HALF_UP
    )
    if delta >= rules.minimum_delta:
        code = "improving"
    elif delta <= -rules.minimum_delta:
        code = "declining"
    else:
        code = "stable"
    return TrendResult(
        code=code,
        delta=delta,
        preceding_average=preceding_average.quantize(
            TREND_QUANTUM, rounding=ROUND_HALF_UP
        ),
        recent_average=recent_average.quantize(
            TREND_QUANTUM, rounding=ROUND_HALF_UP
        ),
        event_ids=event_ids,
    )
