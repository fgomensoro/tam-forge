"""Real-interview text reaches Claude only through a permitted, approved release."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.interviews.redaction import (
    RedactionError,
    RedactionSpan,
    ReleaseApproval,
    build_preview,
    digest,
    redact,
    release_to_claude,
)
from tamforge_protocol.interviews import Interview, RecordingPermission

NOW = datetime(2026, 9, 15, 17, tzinfo=UTC)
TEXT = "Dana at Northwind said the renewal is at risk."
SPANS = (RedactionSpan(0, 4, "person_name"), RedactionSpan(8, 17, "company_name"))


def interview(**overrides: object) -> Interview:
    data: dict[str, object] = {
        "interview_id": 11,
        "owner_id": 1,
        "kind": "real",
        "scheduled_for": NOW - timedelta(hours=2),
        "opportunity_id": 4,
        "stage_label": "Panel",
    }
    data.update(overrides)
    return Interview.model_validate(data)


def permission(**overrides: object) -> RecordingPermission:
    data: dict[str, object] = {
        "interview_id": 11,
        "attested_by": "Interviewer, Northwind",
        "attested_at": NOW - timedelta(hours=3),
        "scopes": ("record_audio", "store_transcript", "release_to_claude"),
    }
    data.update(overrides)
    return RecordingPermission.model_validate(data)


def preview(**overrides: object):
    data: dict[str, object] = {
        "interview": interview(),
        "owner_id": 1,
        "text": TEXT,
        "spans": SPANS,
        "at": NOW,
    }
    data.update(overrides)
    return build_preview(**data)  # type: ignore[arg-type]


def approval(**overrides: object) -> ReleaseApproval:
    data: dict[str, object] = {
        "preview_sha256": preview().preview_sha256,
        "approved_by": "owner",
        "approved_at": NOW,
    }
    data.update(overrides)
    return ReleaseApproval(**data)  # type: ignore[arg-type]


def release(**overrides: object):
    data: dict[str, object] = {
        "interview": interview(),
        "owner_id": 1,
        "permission": permission(),
        "preview": preview(),
        "approval": approval(),
        "now": NOW,
    }
    data.update(overrides)
    return release_to_claude(
        data.pop("interview"),  # type: ignore[arg-type]
        **data,  # type: ignore[arg-type]
    )


def test_a_permitted_and_approved_release_is_recorded() -> None:
    record = release()

    assert record.interview_id == 11
    assert record.owner_id == 1
    assert record.source_sha256 == digest(TEXT)
    assert record.released_sha256 == digest(redact(TEXT, SPANS))
    assert record.approved_by == "owner"
    assert record.released_at == NOW


def test_nothing_is_released_without_the_consent_scope() -> None:
    narrower = permission(scopes=("record_audio", "store_transcript"))

    with pytest.raises(RedactionError, match="scope_not_granted"):
        release(permission=narrower)


def test_nothing_is_released_without_any_permission_at_all() -> None:
    with pytest.raises(RedactionError, match="permission_missing"):
        release(permission=None)


def test_a_revoked_permission_stops_the_release() -> None:
    with pytest.raises(RedactionError, match="permission_revoked"):
        release(permission=permission(revoked_at=NOW - timedelta(minutes=1)))


def test_an_approval_for_different_bytes_authorizes_nothing() -> None:
    # Editing the transcript or recomputing the spans has to invalidate the approval,
    # or approval means nothing in particular.
    other = build_preview(
        interview(), owner_id=1, text=TEXT + " The API is failing too.", spans=SPANS, at=NOW
    )

    with pytest.raises(RedactionError, match="does not match this preview"):
        release(approval=approval(preview_sha256=other.preview_sha256))


def test_an_approval_cannot_predate_the_preview_it_approves() -> None:
    with pytest.raises(RedactionError, match="after it is generated"):
        release(approval=approval(approved_at=NOW - timedelta(minutes=1)))


def test_a_preview_from_another_interview_or_owner_is_refused() -> None:
    elsewhere = build_preview(
        interview(interview_id=12), owner_id=1, text=TEXT, spans=SPANS, at=NOW
    )

    with pytest.raises(RedactionError, match="another interview or owner"):
        release(preview=elsewhere, approval=approval(preview_sha256=elsewhere.preview_sha256))


def test_the_released_bytes_are_the_redacted_ones_and_never_the_source() -> None:
    record = release()

    assert record.released_sha256 != record.source_sha256
    assert record.released_sha256 == digest(redact(TEXT, SPANS))


def test_an_approval_names_who_gave_it_and_what_it_covers() -> None:
    with pytest.raises(RedactionError, match="names who gave it"):
        approval(approved_by="   ")
    with pytest.raises(RedactionError, match="names the preview"):
        approval(preview_sha256="short")
