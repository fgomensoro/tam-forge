"""Quota, auth and worker failures become one content-safe NeedsAttention transition."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from tamforge_backend.observability.attention import (
    NEVER_RETRIED,
    AttentionError,
    AttentionTransition,
    transition,
)
from tamforge_backend.observability.health import COMPONENTS, HealthRegistry

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)  # a Saturday in UTC, a Friday in LA
SECRET = "oauth token CANARY-TOKEN-0123 the learner said something private"


def failed(failure: str, **overrides: object) -> AttentionTransition:
    data: dict[str, object] = {
        "failure": failure,
        "job_id": 42,
        "attempt_count": 1,
        "max_attempts": 3,
        "component": "claude",
        "subject_id": 7,
        "occurred_at": NOW,
        "timezone": "America/Los_Angeles",
    }
    data.update(overrides)
    return transition(**data)  # type: ignore[arg-type]


@pytest.mark.parametrize("failure", sorted(NEVER_RETRIED))
def test_quota_and_expired_auth_are_never_retried_and_mark_the_capability(failure: str) -> None:
    result = failed(failure, attempt_count=1, max_attempts=5)
    assert result.needs_attention
    assert result.component_status == "needs_attention"
    assert result.reason in {"quota", "auth"}
    assert result.notification is not None
    assert result.notification.notification_type == "processing_failure_requires_action"


def test_a_transient_service_failure_retries_inside_its_bound_then_needs_attention() -> None:
    first = failed("service_unavailable", attempt_count=1, max_attempts=3)
    assert first.job_disposition == "retry_wait" and first.component_status == "ok"
    assert first.notification is None
    last = failed("service_unavailable", attempt_count=3, max_attempts=3)
    assert last.needs_attention and last.component_status == "needs_attention"
    assert last.notification is not None


def test_a_crashed_worker_or_invalid_output_needs_attention_without_degrading_the_capability() -> (
    None
):
    for failure in ("worker_crashed", "output_invalid", "turns_exceeded"):
        result = failed(failure)
        assert result.needs_attention and result.component_status == "ok"
        assert result.notification is not None


def test_the_log_line_carries_ids_state_and_reason_and_nothing_else() -> None:
    result = failed("quota_exhausted")
    payload = json.loads(result.log_line)
    assert payload == {
        "event": "job_completed",
        "job_id": 42,
        "status": "needs_attention",
        "error_code": "quota",
    }
    assert SECRET not in result.log_line


def test_a_second_failure_on_the_same_subject_updates_state_but_does_not_notify_again() -> None:
    again = failed("quota_exhausted", already_notified=frozenset({7}))
    assert again.needs_attention and again.notification is None


def test_the_notification_is_one_of_the_approved_types_and_bound_to_the_subject() -> None:
    result = failed("authentication_rejected")
    assert result.notification is not None
    assert (result.notification.subject_kind, result.notification.subject_id) == (
        "processing_status",
        7,
    )


def test_the_health_registry_accepts_every_component_report_this_module_produces() -> None:
    registry = HealthRegistry()
    for component in COMPONENTS:
        registry.report(component, "ok", "none")
    for failure in ("quota_exhausted", "authentication_rejected", "service_unavailable"):
        result = failed(failure, attempt_count=3, max_attempts=3)
        registry.report(result.component, result.component_status, result.reason)
    snapshot = registry.snapshot(database_ready=True)
    # Claude needs attention; independent study stays ready.
    assert snapshot["components"]["claude"] == {"status": "needs_attention", "reason": "service"}
    assert snapshot["ready"] is True


def test_an_unknown_failure_is_refused_rather_than_guessed() -> None:
    with pytest.raises(AttentionError):
        failed("something_new")


def test_error_categories_and_reasons_come_from_the_closed_vocabularies() -> None:
    from tamforge_backend.notifications.models import ERROR_CATEGORIES
    from tamforge_backend.observability.logging import REASONS

    for failure in (
        "quota_exhausted",
        "authentication_rejected",
        "service_unavailable",
        "timeout",
        "output_invalid",
        "turns_exceeded",
        "worker_crashed",
    ):
        result = failed(failure, attempt_count=3, max_attempts=3)
        assert result.error_category in ERROR_CATEGORIES and result.reason in REASONS
