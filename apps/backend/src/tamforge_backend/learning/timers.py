"""Pure server-authoritative focused-time accumulation rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

MAX_HEARTBEAT_GAP_SECONDS = 30
DAY_HARD_STOP_SECONDS = 255 * 60


class TimerPolicyError(ValueError):
    """A timer command would duplicate or corrupt measured focus."""


@dataclass(frozen=True, slots=True)
class TimerState:
    started_at: datetime
    last_heartbeat_at: datetime
    counted_seconds: int
    last_client_sequence: int
    paused_at: datetime | None = None
    ended_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.ended_at is None


@dataclass(frozen=True, slots=True)
class HeartbeatDecision:
    timer: TimerState
    added_seconds: int
    day_counted_seconds: int
    hard_stop_recommended: bool


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def start_timer(server_now: datetime) -> TimerState:
    if not _aware(server_now):
        raise TimerPolicyError("server timestamp must be timezone-aware")
    return TimerState(
        started_at=server_now,
        last_heartbeat_at=server_now,
        counted_seconds=0,
        last_client_sequence=0,
    )


def ensure_single_open_timer(timers: tuple[TimerState, ...]) -> TimerState | None:
    open_timers = tuple(item for item in timers if item.is_open)
    if len(open_timers) > 1:
        raise TimerPolicyError("activity has more than one open timer")
    return open_timers[0] if open_timers else None


def apply_heartbeat(
    timer: TimerState,
    *,
    server_now: datetime,
    client_sequence: int,
    day_counted_seconds: int,
    maximum_gap_seconds: int = MAX_HEARTBEAT_GAP_SECONDS,
    day_hard_stop_seconds: int = DAY_HARD_STOP_SECONDS,
) -> HeartbeatDecision:
    """Count only a bounded server-time delta and advance a monotonic client sequence."""
    if not _aware(server_now):
        raise TimerPolicyError("server timestamp must be timezone-aware")
    if not timer.is_open or timer.paused_at is not None:
        raise TimerPolicyError("timer is not open")
    if client_sequence <= timer.last_client_sequence:
        raise TimerPolicyError("heartbeat sequence must increase")
    if server_now < timer.last_heartbeat_at:
        raise TimerPolicyError("server heartbeat cannot move backward")
    if day_counted_seconds < 0 or day_hard_stop_seconds <= 0:
        raise TimerPolicyError("day timer total is invalid")
    if maximum_gap_seconds <= 0:
        raise TimerPolicyError("heartbeat gap must be positive")
    elapsed_seconds = int((server_now - timer.last_heartbeat_at).total_seconds())
    bounded_seconds = min(elapsed_seconds, maximum_gap_seconds)
    remaining_seconds = max(0, day_hard_stop_seconds - day_counted_seconds)
    added_seconds = min(bounded_seconds, remaining_seconds)
    next_day_seconds = day_counted_seconds + added_seconds
    updated = replace(
        timer,
        last_heartbeat_at=server_now,
        counted_seconds=timer.counted_seconds + added_seconds,
        last_client_sequence=client_sequence,
    )
    return HeartbeatDecision(
        timer=updated,
        added_seconds=added_seconds,
        day_counted_seconds=next_day_seconds,
        hard_stop_recommended=next_day_seconds >= day_hard_stop_seconds,
    )
