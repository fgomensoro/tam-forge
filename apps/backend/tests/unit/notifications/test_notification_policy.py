"""Allowed-notification and Sunday-boundary policy tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


def test_only_five_actionable_notification_types_are_allowed() -> None:
    from tamforge_backend.notifications.policy import (
        NotificationCandidate,
        NotificationPolicyError,
        validate_notification_candidate,
    )

    allowed = (
        "feedback_ready",
        "correction_due",
        "upcoming_real_interview",
        "saturday_assessment",
        "processing_failure_requires_action",
    )
    instant = datetime(2026, 8, 29, 12, tzinfo=UTC)
    for notification_type in allowed:
        validate_notification_candidate(
            NotificationCandidate(
                notification_type=notification_type,
                subject_kind="activity",
                subject_id=7,
                occurred_at=instant,
                timezone="America/Los_Angeles",
            )
        )

    for forbidden in (
        "streak",
        "engagement",
        "generic_inactivity",
        "catch_up",
        "sunday_study_reminder",
    ):
        with pytest.raises(NotificationPolicyError, match="not allowed"):
            validate_notification_candidate(
                NotificationCandidate(
                    notification_type=forbidden,
                    subject_kind="activity",
                    subject_id=7,
                    occurred_at=instant,
                    timezone="America/Los_Angeles",
                )
            )


def test_saturday_and_sunday_rules_use_the_learner_timezone() -> None:
    from tamforge_backend.notifications.policy import (
        NotificationCandidate,
        NotificationPolicyError,
        validate_notification_candidate,
    )

    saturday_los_angeles = datetime(2026, 8, 30, 2, tzinfo=UTC)
    validate_notification_candidate(
        NotificationCandidate(
            notification_type="saturday_assessment",
            subject_kind="study_day",
            subject_id=7,
            occurred_at=saturday_los_angeles,
            timezone="America/Los_Angeles",
        )
    )
    with pytest.raises(NotificationPolicyError, match="Saturday"):
        validate_notification_candidate(
            NotificationCandidate(
                notification_type="saturday_assessment",
                subject_kind="study_day",
                subject_id=7,
                occurred_at=saturday_los_angeles,
                timezone="Asia/Tokyo",
            )
        )

    sunday_los_angeles = datetime(2026, 8, 30, 18, tzinfo=UTC)
    with pytest.raises(NotificationPolicyError, match="Sunday"):
        validate_notification_candidate(
            NotificationCandidate(
                notification_type="correction_due",
                subject_kind="correction",
                subject_id=8,
                occurred_at=sunday_los_angeles,
                timezone="America/Los_Angeles",
            )
        )
    validate_notification_candidate(
        NotificationCandidate(
            notification_type="feedback_ready",
            subject_kind="activity",
            subject_id=9,
            occurred_at=sunday_los_angeles,
            timezone="America/Los_Angeles",
        )
    )


def test_outbox_mapping_rejects_mismatched_or_unapproved_domain_events() -> None:
    from tamforge_backend.notifications.policy import notification_candidate_from_event

    instant = datetime(2026, 8, 29, 12, tzinfo=UTC)
    approved = notification_candidate_from_event(
        event_type="activity.feedback_ready",
        aggregate_type="activity",
        subject_id=7,
        occurred_at=instant,
        timezone="America/Los_Angeles",
    )
    assert approved is not None
    assert approved.notification_type == "feedback_ready"

    assert (
        notification_candidate_from_event(
            event_type="activity.feedback_ready",
            aggregate_type="roadmap",
            subject_id=7,
            occurred_at=instant,
            timezone="America/Los_Angeles",
        )
        is None
    )
    assert (
        notification_candidate_from_event(
            event_type="activity.engagement",
            aggregate_type="activity",
            subject_id=7,
            occurred_at=instant,
            timezone="America/Los_Angeles",
        )
        is None
    )
