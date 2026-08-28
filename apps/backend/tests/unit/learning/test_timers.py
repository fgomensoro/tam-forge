from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.learning.timers import (
    DAY_HARD_STOP_SECONDS,
    MAX_HEARTBEAT_GAP_SECONDS,
    TimerPolicyError,
    apply_heartbeat,
    ensure_single_open_timer,
    start_timer,
)

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)


def test_missing_heartbeat_gap_is_bounded_by_server_policy() -> None:
    timer = start_timer(NOW)

    decision = apply_heartbeat(
        timer,
        server_now=NOW + timedelta(minutes=5),
        client_sequence=1,
        day_counted_seconds=0,
    )

    assert decision.added_seconds == MAX_HEARTBEAT_GAP_SECONDS
    assert decision.timer.counted_seconds == MAX_HEARTBEAT_GAP_SECONDS
    assert decision.timer.last_heartbeat_at == NOW + timedelta(minutes=5)


def test_stale_or_duplicate_client_sequence_cannot_count_twice() -> None:
    first = apply_heartbeat(
        start_timer(NOW),
        server_now=NOW + timedelta(seconds=10),
        client_sequence=1,
        day_counted_seconds=0,
    )

    with pytest.raises(TimerPolicyError, match="sequence"):
        apply_heartbeat(
            first.timer,
            server_now=NOW + timedelta(seconds=20),
            client_sequence=1,
            day_counted_seconds=10,
        )


def test_two_open_timers_for_one_activity_are_rejected() -> None:
    timer = start_timer(NOW)
    with pytest.raises(TimerPolicyError, match="open timer"):
        ensure_single_open_timer((timer, start_timer(NOW + timedelta(seconds=1))))


def test_timer_state_survives_reload_without_recounting_old_time() -> None:
    first = apply_heartbeat(
        start_timer(NOW),
        server_now=NOW + timedelta(seconds=10),
        client_sequence=1,
        day_counted_seconds=0,
    )
    reloaded = first.timer

    second = apply_heartbeat(
        reloaded,
        server_now=NOW + timedelta(seconds=25),
        client_sequence=2,
        day_counted_seconds=first.timer.counted_seconds,
    )

    assert second.added_seconds == 15
    assert second.timer.counted_seconds == 25


def test_hard_stop_is_recommended_and_time_is_not_extended_past_255_minutes() -> None:
    timer = start_timer(NOW)

    decision = apply_heartbeat(
        timer,
        server_now=NOW + timedelta(seconds=30),
        client_sequence=1,
        day_counted_seconds=DAY_HARD_STOP_SECONDS - 5,
    )

    assert decision.added_seconds == 5
    assert decision.hard_stop_recommended
    assert decision.day_counted_seconds == DAY_HARD_STOP_SECONDS


def test_server_clock_and_timer_lifecycle_are_authoritative() -> None:
    timer = start_timer(NOW)
    with pytest.raises(TimerPolicyError, match="timezone-aware"):
        apply_heartbeat(
            timer,
            server_now=datetime(2026, 8, 27, 12),
            client_sequence=1,
            day_counted_seconds=0,
        )
    with pytest.raises(TimerPolicyError, match="backward"):
        apply_heartbeat(
            timer,
            server_now=NOW - timedelta(seconds=1),
            client_sequence=1,
            day_counted_seconds=0,
        )
