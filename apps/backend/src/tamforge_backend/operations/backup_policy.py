"""The approved backup policy, as rules a drill result can be checked against.

Backups are taken daily, encrypted before they leave the host, versioned so an earlier
restore point survives a later bad one, and kept on a rotation that is separate from how
long the learner's own material is retained: seven daily, five weekly, twelve monthly
restore points. Application archive and deletion never prune a backup, and backup expiry
never touches a canonical row; the two policies do not know about each other.

The policy also fixes the two numbers a restore drill must meet. RPO is the age of the
newest thing in the backup at drill time, and with a daily cadence it may be a day plus
an hour of slack; RTO is how long the restore took, and it may not exceed an hour. A drill
that misses either fails, and a drill that ran against production is not evidence at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

CADENCE: Final = timedelta(days=1)
RETENTION_DAILY: Final = 7
RETENTION_WEEKLY: Final = 5
RETENTION_MONTHLY: Final = 12
MAX_RPO_MINUTES: Final = 24 * 60 + 60
MAX_RTO_MINUTES: Final = 60

Cipher = Literal["AES-256-GCM"]


class BackupPolicyError(ValueError):
    """A backup, restore point or drill that the policy does not accept."""


@dataclass(frozen=True, slots=True)
class BackupPolicy:
    cadence: timedelta = CADENCE
    encrypted_with: Cipher = "AES-256-GCM"
    versioned: bool = True
    keep_daily: int = RETENTION_DAILY
    keep_weekly: int = RETENTION_WEEKLY
    keep_monthly: int = RETENTION_MONTHLY
    max_rpo_minutes: int = MAX_RPO_MINUTES
    max_rto_minutes: int = MAX_RTO_MINUTES

    def __post_init__(self) -> None:
        if self.cadence <= timedelta(0):
            raise BackupPolicyError("cadence is positive")
        if not self.versioned:
            raise BackupPolicyError("backups are versioned; an overwrite is not a backup")
        if min(self.keep_daily, self.keep_weekly, self.keep_monthly) < 1:
            raise BackupPolicyError("every rotation tier keeps at least one restore point")
        if self.max_rpo_minutes < int(self.cadence / timedelta(minutes=1)):
            raise BackupPolicyError("the RPO bound cannot be tighter than the cadence")

    def is_due(self, *, last_backup_at: datetime | None, now: datetime) -> bool:
        return last_backup_at is None or now - last_backup_at >= self.cadence


APPROVED: Final = BackupPolicy()


@dataclass(frozen=True, slots=True)
class RestorePoint:
    """One completed, verified backup. Malformed metadata means `verified` is False."""

    name: str
    captured_at: datetime
    encrypted: bool
    verified: bool
    prefix: str


def keep_set(
    points: tuple[RestorePoint, ...], *, policy: BackupPolicy, now: datetime
) -> frozenset[str]:
    """Which restore points the rotation keeps. The newest valid one is always kept."""
    valid = sorted(
        (p for p in points if p.verified and p.encrypted), key=lambda p: p.captured_at, reverse=True
    )
    keep: set[str] = set()
    if valid:
        keep.add(valid[0].name)
    keep.update(p.name for p in valid[: policy.keep_daily])
    weeks: dict[tuple[int, int], RestorePoint] = {}
    months: dict[tuple[int, int], RestorePoint] = {}
    for p in valid:
        iso = p.captured_at.isocalendar()
        weeks.setdefault((iso.year, iso.week), p)
        months.setdefault((p.captured_at.year, p.captured_at.month), p)
    keep.update(p.name for p in list(weeks.values())[: policy.keep_weekly])
    keep.update(p.name for p in list(months.values())[: policy.keep_monthly])
    # Anything unverified is never pruned by rotation: a malformed entry is a question,
    # not a deletion.
    keep.update(p.name for p in points if not p.verified)
    return frozenset(keep)


def prune_candidates(
    points: tuple[RestorePoint, ...], *, policy: BackupPolicy, now: datetime, prefix: str
) -> tuple[str, ...]:
    """Names rotation may remove: only under the dedicated prefix, never the keep set."""
    if not prefix.endswith("/") or prefix in ("/", ""):
        raise BackupPolicyError("prune operates on one fully resolved backup prefix")
    outside = [p.name for p in points if p.prefix != prefix]
    if outside:
        raise BackupPolicyError(f"restore points outside the backup prefix: {outside}")
    keep = keep_set(points, policy=policy, now=now)
    return tuple(sorted(p.name for p in points if p.name not in keep))


@dataclass(frozen=True, slots=True)
class DrillEvidence:
    environment: str
    is_production: bool
    verified_artifacts: int
    rpo_minutes: int
    rto_minutes: int
    encrypted: bool


def evidence_meets(policy: BackupPolicy, evidence: DrillEvidence) -> tuple[str, ...]:
    """The reasons the evidence falls short; empty means it meets the policy."""
    reasons: list[str] = []
    if evidence.is_production:
        reasons.append("the drill ran against production and proves nothing")
    if evidence.verified_artifacts < 1:
        reasons.append("no artifact was verified")
    if not evidence.encrypted:
        reasons.append("the backup was not encrypted")
    if evidence.rpo_minutes > policy.max_rpo_minutes:
        reasons.append(f"RPO {evidence.rpo_minutes} min exceeds {policy.max_rpo_minutes}")
    if evidence.rto_minutes > policy.max_rto_minutes:
        reasons.append(f"RTO {evidence.rto_minutes} min exceeds {policy.max_rto_minutes}")
    return tuple(reasons)


__all__ = [
    "APPROVED",
    "CADENCE",
    "MAX_RPO_MINUTES",
    "MAX_RTO_MINUTES",
    "RETENTION_DAILY",
    "RETENTION_MONTHLY",
    "RETENTION_WEEKLY",
    "BackupPolicy",
    "BackupPolicyError",
    "DrillEvidence",
    "RestorePoint",
    "evidence_meets",
    "keep_set",
    "prune_candidates",
]
