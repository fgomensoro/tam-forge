"""Allowlist and learner-local calendar rules for notifications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import NOTIFICATION_TYPES, SUBJECT_KINDS


class NotificationPolicyError(ValueError):
    """A proposed notification is not actionable under learner policy."""


@dataclass(frozen=True, slots=True)
class NotificationCandidate:
    notification_type: str
    subject_kind: str
    subject_id: int
    occurred_at: datetime
    timezone: str


_EVENT_MAPPING = {
    ("activity.feedback_ready", "activity"): ("feedback_ready", "activity"),
    ("correction.due", "correction"): ("correction_due", "correction"),
    ("interview.upcoming", "interview"): (
        "upcoming_real_interview",
        "interview",
    ),
    ("study_day.saturday_assessment", "study_day"): (
        "saturday_assessment",
        "study_day",
    ),
    ("processing_status.needs_attention", "processing_status"): (
        "processing_failure_requires_action",
        "processing_status",
    ),
}


def validate_notification_candidate(candidate: NotificationCandidate) -> None:
    if candidate.notification_type not in NOTIFICATION_TYPES:
        raise NotificationPolicyError("notification type is not allowed")
    if candidate.subject_kind not in SUBJECT_KINDS or candidate.subject_id <= 0:
        raise NotificationPolicyError("notification subject is invalid")
    if (
        candidate.occurred_at.tzinfo is None
        or candidate.occurred_at.utcoffset() is None
    ):
        raise NotificationPolicyError("notification timestamp must be timezone-aware")
    try:
        local = candidate.occurred_at.astimezone(ZoneInfo(candidate.timezone))
    except (ZoneInfoNotFoundError, ValueError):
        raise NotificationPolicyError("learner timezone is invalid") from None
    if candidate.notification_type == "saturday_assessment" and local.weekday() != 5:
        raise NotificationPolicyError("Saturday assessment notification requires Saturday")
    if candidate.notification_type == "correction_due" and local.weekday() == 6:
        raise NotificationPolicyError("Sunday correction reminders are disabled")


def notification_candidate_from_event(
    *,
    event_type: str,
    aggregate_type: str,
    subject_id: int,
    occurred_at: datetime,
    timezone: str,
) -> NotificationCandidate | None:
    mapped = _EVENT_MAPPING.get((event_type, aggregate_type))
    if mapped is None:
        return None
    candidate = NotificationCandidate(
        notification_type=mapped[0],
        subject_kind=mapped[1],
        subject_id=subject_id,
        occurred_at=occurred_at,
        timezone=timezone,
    )
    try:
        validate_notification_candidate(candidate)
    except NotificationPolicyError:
        return None
    return candidate


__all__ = [
    "NotificationCandidate",
    "NotificationPolicyError",
    "notification_candidate_from_event",
    "validate_notification_candidate",
]
