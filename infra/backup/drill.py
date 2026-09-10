"""A restore drill that runs somewhere else, and reports numbers rather than a feeling.

A backup nobody has restored is a hypothesis. This is the loop that turns it into a
measurement, and everything about it is arranged so the measurement cannot flatter the
system.

It runs in a clean environment and refuses to run anywhere marked production. The point
of the drill is to prove the backup is sufficient on its own, and a drill that quietly
borrows a running database, a cached credential or a warm filesystem proves the opposite
of what it claims to.

It reports two numbers against thresholds someone approved beforehand. RPO is how much
work the backup would have lost: the age of the newest thing in it. RTO is how long the
restore actually took. Both are measured from the drill, never estimated, and a drill
that misses either threshold fails rather than recording a note.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta


class DrillError(ValueError):
    """The drill cannot run, or cannot claim what it is about to claim."""


class ProductionRefused(DrillError):
    """Somebody pointed the restore drill at the live system."""


@dataclass(frozen=True, slots=True)
class Environment:
    """Where the drill is about to write. Named, so refusing is possible."""

    name: str
    is_production: bool

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DrillError("an environment has a name")


@dataclass(frozen=True, slots=True)
class Thresholds:
    """What was agreed before anyone knew how the drill would go."""

    max_rpo_minutes: int
    max_rto_minutes: int

    def __post_init__(self) -> None:
        if self.max_rpo_minutes < 1 or self.max_rto_minutes < 1:
            raise DrillError("thresholds are positive numbers of minutes")


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    path: str
    sha256: str
    captured_at: datetime

    def __post_init__(self) -> None:
        if len(self.sha256) != 64:
            raise DrillError("a backup artifact carries its hash")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise DrillError("backup timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DrillResult:
    environment: str
    verified: int
    rpo_minutes: int
    rto_minutes: int
    thresholds: Thresholds

    @property
    def met(self) -> bool:
        return (
            self.rpo_minutes <= self.thresholds.max_rpo_minutes
            and self.rto_minutes <= self.thresholds.max_rto_minutes
        )

    @property
    def missed(self) -> tuple[str, ...]:
        misses = []
        if self.rpo_minutes > self.thresholds.max_rpo_minutes:
            misses.append("rpo")
        if self.rto_minutes > self.thresholds.max_rto_minutes:
            misses.append("rto")
        return tuple(misses)


def require_clean_environment(environment: Environment) -> None:
    """Raise if the drill would touch the live system."""
    if environment.is_production:
        raise ProductionRefused("a restore drill never runs against production")


def verify_backup(
    artifacts: tuple[BackupArtifact, ...], *, digests: Mapping[str, str]
) -> int:
    """Check every artifact against the bytes present, and return how many held."""
    if not artifacts:
        raise DrillError("an empty backup proves nothing")
    for artifact in artifacts:
        actual = digests.get(artifact.path)
        if actual is None:
            raise DrillError(f"missing from the backup: {artifact.path}")
        if actual != artifact.sha256:
            raise DrillError(f"content does not match its hash: {artifact.path}")
    return len(artifacts)


def run_drill(
    artifacts: tuple[BackupArtifact, ...],
    *,
    environment: Environment,
    digests: Mapping[str, str],
    thresholds: Thresholds,
    started_at: datetime,
    finished_at: datetime,
    now: datetime,
) -> DrillResult:
    """Verify, measure, and report. Refuses before it touches anything."""
    require_clean_environment(environment)
    if finished_at < started_at:
        raise DrillError("a restore cannot finish before it starts")
    verified = verify_backup(artifacts, digests=digests)
    newest = max(artifact.captured_at for artifact in artifacts)
    if now < newest:
        raise DrillError("the backup claims to hold something from the future")
    return DrillResult(
        environment=environment.name,
        verified=verified,
        rpo_minutes=int((now - newest) / timedelta(minutes=1)),
        rto_minutes=int((finished_at - started_at) / timedelta(minutes=1)),
        thresholds=thresholds,
    )


__all__ = [
    "BackupArtifact",
    "DrillError",
    "DrillResult",
    "Environment",
    "ProductionRefused",
    "Thresholds",
    "require_clean_environment",
    "run_drill",
    "verify_backup",
]
