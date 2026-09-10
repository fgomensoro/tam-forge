"""Nothing from a real interview reaches Claude until a person has seen what would go.

A redaction preview is not a promise about the text, it is a statement about exact bytes.
It carries the hash of the source it was computed from and the hash of what it would
produce, and an approval names that second hash. Approving one preview therefore cannot
authorize a different one: edit the transcript, or recompute the spans, and the approval
stops matching and the release stops being allowed.

The release itself is a record rather than an event. Who approved it, of what, and when,
kept beside the release, because the question that matters months later is not whether a
release happened but what exactly was in it.

Consent and approval are separate gates and both are required. The interview permission
says this material may go to Claude at all; the approval says this particular redaction of
it may. Neither substitutes for the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from tamforge_protocol.interviews import Interview, RecordingPermission, recording_lock

# What a span covers. Closed, because "other" as a catch-all is how a category nobody
# reviews accumulates everything difficult.
RedactionCategory = Literal[
    "person_name",
    "company_name",
    "contact_detail",
    "account_identifier",
    "financial_figure",
]

REDACTION_PLACEHOLDER = "[redacted]"


class RedactionError(ValueError):
    """A release that would send something nobody approved."""


@dataclass(frozen=True, slots=True)
class RedactionSpan:
    start: int
    end: int
    category: RedactionCategory

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise RedactionError("a span covers a nonempty range")


def redact(text: str, spans: tuple[RedactionSpan, ...]) -> str:
    """Apply spans right to left so earlier offsets stay valid as the text shrinks."""
    ordered = sorted(spans, key=lambda span: span.start)
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if later.start < earlier.end:
            raise RedactionError("spans overlap, so what would be sent is ambiguous")
    if ordered and ordered[-1].end > len(text):
        raise RedactionError("a span runs past the end of the text")
    redacted = text
    for span in reversed(ordered):
        redacted = redacted[: span.start] + REDACTION_PLACEHOLDER + redacted[span.end :]
    return redacted


def digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RedactionPreview:
    """What would be sent, pinned to the exact bytes it was computed from."""

    interview_id: int
    owner_id: int
    source_sha256: str
    preview_sha256: str
    spans: tuple[RedactionSpan, ...]
    generated_at: datetime

    def __post_init__(self) -> None:
        if len(self.source_sha256) != 64 or len(self.preview_sha256) != 64:
            raise RedactionError("a preview pins both the source and what it produces")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise RedactionError("preview timestamps must be timezone-aware")


def build_preview(
    interview: Interview,
    *,
    owner_id: int,
    text: str,
    spans: tuple[RedactionSpan, ...],
    at: datetime,
) -> RedactionPreview:
    return RedactionPreview(
        interview_id=interview.interview_id,
        owner_id=owner_id,
        source_sha256=digest(text),
        preview_sha256=digest(redact(text, spans)),
        spans=spans,
        generated_at=at,
    )


@dataclass(frozen=True, slots=True)
class ReleaseApproval:
    """A person approving one specific preview, named by what it would produce."""

    preview_sha256: str
    approved_by: str
    approved_at: datetime

    def __post_init__(self) -> None:
        if len(self.preview_sha256) != 64:
            raise RedactionError("an approval names the preview it approves")
        if not self.approved_by.strip():
            raise RedactionError("an approval names who gave it")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise RedactionError("approval timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    """The audit trail of one release: what went, who allowed it, and when."""

    interview_id: int
    owner_id: int
    source_sha256: str
    released_sha256: str
    approved_by: str
    released_at: datetime


def release_to_claude(
    interview: Interview,
    *,
    owner_id: int,
    permission: RecordingPermission | None,
    preview: RedactionPreview,
    approval: ReleaseApproval,
    now: datetime,
) -> ReleaseRecord:
    """Return the audit record for a permitted, approved release, or refuse it."""
    if preview.interview_id != interview.interview_id or preview.owner_id != owner_id:
        raise RedactionError("that preview belongs to another interview or owner")
    state, reason = recording_lock(
        interview, permission, scope="release_to_claude", now=now
    )
    if state != "unlocked":
        raise RedactionError(f"release is not permitted: {reason}")
    if approval.preview_sha256 != preview.preview_sha256:
        # The approval was for different bytes. Editing the transcript or recomputing
        # the spans has to invalidate it, or approval means nothing in particular.
        raise RedactionError("the approval does not match this preview")
    if approval.approved_at < preview.generated_at:
        raise RedactionError("a preview is approved after it is generated, not before")
    return ReleaseRecord(
        interview_id=interview.interview_id,
        owner_id=owner_id,
        source_sha256=preview.source_sha256,
        released_sha256=preview.preview_sha256,
        approved_by=approval.approved_by,
        released_at=now,
    )


__all__ = [
    "REDACTION_PLACEHOLDER",
    "RedactionCategory",
    "RedactionError",
    "RedactionPreview",
    "RedactionSpan",
    "ReleaseApproval",
    "ReleaseRecord",
    "build_preview",
    "digest",
    "redact",
    "release_to_claude",
]
