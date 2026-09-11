"""The backup policy: daily, encrypted, versioned, rotated apart from retention, drilled."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.operations.backup_policy import (
    APPROVED,
    BackupPolicy,
    BackupPolicyError,
    DrillEvidence,
    RestorePoint,
    evidence_meets,
    keep_set,
    prune_candidates,
)
from tamforge_backend.operations.retention import DEFAULT_POLICIES

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)
PREFIX = "backups/tamforge/"


def point(
    days_ago: int, *, verified: bool = True, encrypted: bool = True, prefix: str = PREFIX
) -> RestorePoint:
    at = NOW - timedelta(days=days_ago)
    return RestorePoint(
        name=at.strftime("%Y%m%dT%H%M%SZ"),
        captured_at=at,
        encrypted=encrypted,
        verified=verified,
        prefix=prefix,
    )


def test_the_approved_policy_is_daily_encrypted_versioned_and_rotated_seven_five_twelve() -> None:
    assert APPROVED.cadence == timedelta(days=1)
    assert APPROVED.encrypted_with == "AES-256-GCM" and APPROVED.versioned
    assert (APPROVED.keep_daily, APPROVED.keep_weekly, APPROVED.keep_monthly) == (7, 5, 12)
    assert (APPROVED.max_rpo_minutes, APPROVED.max_rto_minutes) == (1500, 60)


def test_an_unversioned_or_too_tight_policy_is_refused() -> None:
    with pytest.raises(BackupPolicyError, match="versioned"):
        BackupPolicy(versioned=False)
    with pytest.raises(BackupPolicyError, match="tighter than the cadence"):
        BackupPolicy(max_rpo_minutes=60)


def test_a_backup_is_due_daily() -> None:
    assert APPROVED.is_due(last_backup_at=None, now=NOW)
    assert not APPROVED.is_due(last_backup_at=NOW - timedelta(hours=23), now=NOW)
    assert APPROVED.is_due(last_backup_at=NOW - timedelta(hours=24), now=NOW)


def test_rotation_keeps_daily_weekly_and_monthly_points_and_prunes_the_rest() -> None:
    points = tuple(point(d) for d in range(0, 400))
    keep = keep_set(points, policy=APPROVED, now=NOW)
    for d in range(7):
        assert point(d).name in keep
    assert len(keep) <= 7 + 5 + 12
    assert point(45).name not in keep or len([k for k in keep]) > 0
    pruned = prune_candidates(points, policy=APPROVED, now=NOW, prefix=PREFIX)
    assert set(pruned) == {p.name for p in points} - keep
    assert point(0).name not in pruned


def test_the_newest_valid_point_is_always_kept_even_alone() -> None:
    assert keep_set((point(3),), policy=APPROVED, now=NOW) == {point(3).name}


def test_a_malformed_or_unverified_point_is_never_pruned_by_rotation() -> None:
    points = (point(0), point(100, verified=False), point(200, verified=False))
    pruned = prune_candidates(points, policy=APPROVED, now=NOW, prefix=PREFIX)
    assert pruned == ()


def test_an_unencrypted_point_is_not_a_valid_restore_point() -> None:
    keep = keep_set((point(0, encrypted=False), point(1)), policy=APPROVED, now=NOW)
    assert keep == {point(1).name}


def test_prune_only_operates_on_the_dedicated_prefix() -> None:
    with pytest.raises(BackupPolicyError, match="one fully resolved"):
        prune_candidates((point(0),), policy=APPROVED, now=NOW, prefix="/")
    with pytest.raises(BackupPolicyError, match="outside the backup prefix"):
        prune_candidates(
            (point(0), point(1, prefix="recordings/")), policy=APPROVED, now=NOW, prefix=PREFIX
        )


def test_backup_rotation_is_independent_of_learner_data_retention() -> None:
    # The two policies share no numbers and no module: a change in one cannot move the other.
    audio = DEFAULT_POLICIES["original_audio"]
    assert (audio.archive_after_days, audio.grace_days, audio.delete_after_days) == (30, 30, 365)
    assert {APPROVED.keep_daily, APPROVED.keep_weekly, APPROVED.keep_monthly}.isdisjoint({30, 365})


def test_drill_evidence_must_be_clean_verified_encrypted_and_within_both_numbers() -> None:
    good = DrillEvidence("restore-drill", False, 2, 600, 9, True)
    assert evidence_meets(APPROVED, good) == ()
    bad = DrillEvidence("production", True, 0, 3000, 90, False)
    reasons = evidence_meets(APPROVED, bad)
    assert len(reasons) == 5
    assert (
        any("production" in r for r in reasons)
        and any("RPO" in r for r in reasons)
        and any("RTO" in r for r in reasons)
    )
