"""Retention by sensitivity, and deletion that a person has to ask for twice.

Three rules shape everything here, and each exists because the alternative is
unrecoverable.

Nothing is deleted because time passed. A policy can say a class of material is due, and
being due is the beginning of a request, never the end of one. Deletion needs an explicit
approval from a person, and then a grace period during which the request can still be
withdrawn, because the moment someone regrets a deletion is usually the moment after
approving it.

Archiving never overwrites. It produces a new record that points at the original by id
and content hash, so the original stays exactly as it was and the archive can be checked
against it later. Deletion is the same shape: what it leaves behind is a tombstone
carrying the identity and hash of what was removed, so the record of what existed
survives the content. Evidence that can be silently overwritten is not evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Literal

# What kind of material a policy governs. Ordered from the most sensitive down, which is
# also the order in which the grace periods get longer.
Sensitivity = Literal[
    "original_audio",
    "transcript",
    "derived_analysis",
    "operational_log",
]

DeletionState = Literal["requested", "approved", "withdrawn", "effective"]


class RetentionError(ValueError):
    """A retention decision that would lose something it cannot get back."""


class ApprovalRequired(RetentionError):
    """Deletion was asked for, but nobody approved it."""


class StillRecoverable(RetentionError):
    """The grace period has not run out, so the request can still be withdrawn."""


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """How long one class of material is kept, and how long regret has to act."""

    sensitivity: Sensitivity
    archive_after_days: int
    grace_days: int
    delete_after_days: int | None = None

    def __post_init__(self) -> None:
        if self.archive_after_days < 1 or self.grace_days < 1:
            raise RetentionError("archive and grace periods must be positive")
        if self.delete_after_days is not None:
            if self.delete_after_days < self.archive_after_days:
                raise RetentionError("material is archived before it is ever due for deletion")


# Original audio is the one thing that cannot be reconstructed from anything else, so it
# gets the longest grace. An operational log carries no owner content and gets the
# shortest. `delete_after_days=None` means a class is never due for deletion at all.
DEFAULT_POLICIES: Mapping[Sensitivity, RetentionPolicy] = MappingProxyType(
    {
        "original_audio": RetentionPolicy("original_audio", 30, 30, 365),
        "transcript": RetentionPolicy("transcript", 90, 14, 730),
        "derived_analysis": RetentionPolicy("derived_analysis", 180, 14, None),
        "operational_log": RetentionPolicy("operational_log", 7, 7, 90),
    }
)


@dataclass(frozen=True, slots=True)
class ArchiveRecord:
    """A pointer to the original, never a replacement for it."""

    subject_id: str
    sensitivity: Sensitivity
    content_sha256: str
    archived_at: datetime
    archive_location: str

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.archive_location.strip():
            raise RetentionError("an archive record identifies what it archived and where")
        if len(self.content_sha256) != 64:
            raise RetentionError("an archive record pins the content it copied")


@dataclass(frozen=True, slots=True)
class Tombstone:
    """What deletion leaves behind: the identity, never the content."""

    subject_id: str
    sensitivity: Sensitivity
    content_sha256: str
    deleted_at: datetime
    approved_by: str
    archive_location: str | None

    def __post_init__(self) -> None:
        if not self.approved_by.strip():
            raise RetentionError("a tombstone names who approved the deletion")


@dataclass(frozen=True, slots=True)
class DeletionRequest:
    """One request, and every step it has to clear before anything is removed."""

    subject_id: str
    sensitivity: Sensitivity
    requested_at: datetime
    approved_at: datetime | None = None
    approved_by: str | None = None
    withdrawn_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.subject_id.strip():
            raise RetentionError("a deletion request names its subject")
        if (self.approved_at is None) != (self.approved_by is None):
            raise RetentionError("an approval has both a time and a person")
        for moment in (self.approved_at, self.withdrawn_at, self.requested_at):
            if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
                raise RetentionError("retention timestamps must be timezone-aware")
        if self.approved_at is not None and self.approved_at < self.requested_at:
            raise RetentionError("an approval cannot precede its request")

    @property
    def state(self) -> DeletionState:
        if self.withdrawn_at is not None:
            return "withdrawn"
        return "approved" if self.approved_at is not None else "requested"

    def effective_at(self, policy: RetentionPolicy) -> datetime:
        """When this may actually be carried out. Approval starts the clock, not the request."""
        if self.approved_at is None:
            raise ApprovalRequired("deletion has not been approved")
        return self.approved_at + timedelta(days=policy.grace_days)


def due_for_archive(*, created_at: datetime, now: datetime, policy: RetentionPolicy) -> bool:
    return now - created_at >= timedelta(days=policy.archive_after_days)


def due_for_deletion(*, created_at: datetime, now: datetime, policy: RetentionPolicy) -> bool:
    """Due means a person may be asked. It never means anything is removed."""
    if policy.delete_after_days is None:
        return False
    return now - created_at >= timedelta(days=policy.delete_after_days)


def archive(
    *, subject_id: str, sensitivity: Sensitivity, content_sha256: str, at: datetime, location: str
) -> ArchiveRecord:
    """Copy a subject into the archive. The original is untouched by construction."""
    return ArchiveRecord(
        subject_id=subject_id,
        sensitivity=sensitivity,
        content_sha256=content_sha256,
        archived_at=at,
        archive_location=location,
    )


def carry_out(
    request: DeletionRequest,
    *,
    policy: RetentionPolicy,
    now: datetime,
    content_sha256: str,
    archive_record: ArchiveRecord | None,
) -> Tombstone:
    """Remove a subject, or refuse and say which guarantee is not satisfied yet."""
    if request.state == "withdrawn":
        raise RetentionError("a withdrawn request deletes nothing")
    if request.approved_at is None or request.approved_by is None:
        raise ApprovalRequired("deletion has not been approved")
    if now < request.effective_at(policy):
        raise StillRecoverable("the grace period has not run out")
    if policy.sensitivity != request.sensitivity:
        raise RetentionError("this policy governs a different kind of material")
    if archive_record is None and policy.delete_after_days is not None:
        # Recoverability is the point. Deleting the only copy of governed material is
        # exactly the operation this module exists to prevent.
        raise RetentionError("nothing may be deleted before it has been archived")
    if archive_record is not None and archive_record.content_sha256 != content_sha256:
        raise RetentionError("the archive does not hold the content being deleted")
    return Tombstone(
        subject_id=request.subject_id,
        sensitivity=request.sensitivity,
        content_sha256=content_sha256,
        deleted_at=now,
        approved_by=request.approved_by,
        archive_location=archive_record.archive_location if archive_record else None,
    )


__all__ = [
    "DEFAULT_POLICIES",
    "ApprovalRequired",
    "ArchiveRecord",
    "DeletionRequest",
    "DeletionState",
    "RetentionError",
    "RetentionPolicy",
    "Sensitivity",
    "StillRecoverable",
    "Tombstone",
    "archive",
    "carry_out",
    "due_for_archive",
    "due_for_deletion",
]
