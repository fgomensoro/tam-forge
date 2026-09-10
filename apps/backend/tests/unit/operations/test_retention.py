"""Archive by sensitivity, delete only on approval and grace, and never overwrite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tamforge_backend.operations.retention import (
    DEFAULT_POLICIES,
    ApprovalRequired,
    ArchiveRecord,
    DeletionRequest,
    RetentionError,
    RetentionPolicy,
    StillRecoverable,
    archive,
    carry_out,
    due_for_archive,
    due_for_deletion,
)

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
DIGEST = "a" * 64


def policy(sensitivity: str = "original_audio") -> RetentionPolicy:
    return DEFAULT_POLICIES[sensitivity]  # type: ignore[index]


def request(**overrides: object) -> DeletionRequest:
    data: dict[str, object] = {
        "subject_id": "recording-11",
        "sensitivity": "original_audio",
        "requested_at": NOW,
        "approved_at": NOW,
        "approved_by": "owner",
    }
    data.update(overrides)
    return DeletionRequest(**data)  # type: ignore[arg-type]


def archived(**overrides: object) -> ArchiveRecord:
    data: dict[str, object] = {
        "subject_id": "recording-11",
        "sensitivity": "original_audio",
        "content_sha256": DIGEST,
        "at": NOW,
        "location": "s3://archive/recording-11",
    }
    data.update(overrides)
    return archive(**data)  # type: ignore[arg-type]


def test_every_governed_kind_has_a_policy_with_a_real_grace_period() -> None:
    assert set(DEFAULT_POLICIES) == {
        "original_audio",
        "transcript",
        "derived_analysis",
        "operational_log",
    }
    for sensitivity, configured in DEFAULT_POLICIES.items():
        assert configured.sensitivity == sensitivity
        assert configured.grace_days >= 1
        assert configured.archive_after_days >= 1


def test_original_audio_gets_the_longest_grace() -> None:
    # It is the one thing that cannot be reconstructed from anything else.
    longest = max(DEFAULT_POLICIES.values(), key=lambda item: item.grace_days)
    assert longest.sensitivity == "original_audio"


def test_derived_analysis_is_archived_but_never_due_for_deletion() -> None:
    derived = policy("derived_analysis")

    assert derived.delete_after_days is None
    assert due_for_archive(created_at=NOW - timedelta(days=200), now=NOW, policy=derived)
    assert not due_for_deletion(created_at=NOW - timedelta(days=9999), now=NOW, policy=derived)


def test_being_due_removes_nothing_by_itself() -> None:
    old = NOW - timedelta(days=400)

    assert due_for_deletion(created_at=old, now=NOW, policy=policy()) is True
    # Due is the beginning of a request, never the end of one.
    with pytest.raises(ApprovalRequired):
        carry_out(
            request(approved_at=None, approved_by=None),
            policy=policy(),
            now=NOW,
            content_sha256=DIGEST,
            archive_record=archived(),
        )


def test_a_deletion_waits_out_its_grace_period() -> None:
    effective = request().effective_at(policy())
    assert effective == NOW + timedelta(days=policy().grace_days)

    with pytest.raises(StillRecoverable):
        carry_out(
            request(),
            policy=policy(),
            now=effective - timedelta(seconds=1),
            content_sha256=DIGEST,
            archive_record=archived(),
        )

    tombstone = carry_out(
        request(), policy=policy(), now=effective, content_sha256=DIGEST, archive_record=archived()
    )
    assert tombstone.subject_id == "recording-11"


def test_a_withdrawn_request_deletes_nothing_even_after_the_grace_period() -> None:
    withdrawn = request(withdrawn_at=NOW + timedelta(days=1))

    assert withdrawn.state == "withdrawn"
    with pytest.raises(RetentionError, match="withdrawn"):
        carry_out(
            withdrawn,
            policy=policy(),
            now=NOW + timedelta(days=90),
            content_sha256=DIGEST,
            archive_record=archived(),
        )


def test_nothing_governed_is_deleted_before_it_is_archived() -> None:
    with pytest.raises(RetentionError, match="archived"):
        carry_out(
            request(),
            policy=policy(),
            now=NOW + timedelta(days=90),
            content_sha256=DIGEST,
            archive_record=None,
        )


def test_an_archive_of_different_content_does_not_make_a_deletion_recoverable() -> None:
    with pytest.raises(RetentionError, match="does not hold"):
        carry_out(
            request(),
            policy=policy(),
            now=NOW + timedelta(days=90),
            content_sha256="b" * 64,
            archive_record=archived(),
        )


def test_archiving_points_at_the_original_rather_than_replacing_it() -> None:
    record = archived()

    assert record.subject_id == "recording-11"
    assert record.content_sha256 == DIGEST
    assert record.archive_location.startswith("s3://")


def test_a_tombstone_keeps_the_identity_and_never_the_content() -> None:
    tombstone = carry_out(
        request(),
        policy=policy(),
        now=NOW + timedelta(days=90),
        content_sha256=DIGEST,
        archive_record=archived(),
    )

    assert tombstone.content_sha256 == DIGEST
    assert tombstone.approved_by == "owner"
    assert tombstone.archive_location == "s3://archive/recording-11"
    assert not hasattr(tombstone, "content")


def test_a_policy_for_another_kind_of_material_cannot_authorize_this_deletion() -> None:
    with pytest.raises(RetentionError, match="different kind"):
        carry_out(
            request(),
            policy=policy("transcript"),
            now=NOW + timedelta(days=90),
            content_sha256=DIGEST,
            archive_record=archived(),
        )


def test_an_approval_has_both_a_time_and_a_person() -> None:
    for changes in ({"approved_by": None}, {"approved_at": None}):
        with pytest.raises(RetentionError, match="both a time and a person"):
            request(**changes)


def test_an_approval_cannot_precede_its_request() -> None:
    with pytest.raises(RetentionError, match="precede"):
        request(approved_at=NOW - timedelta(days=1))


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(RetentionError, match="timezone-aware"):
        request(requested_at=datetime(2026, 9, 10, 12), approved_at=None, approved_by=None)


def test_a_policy_that_deletes_before_it_archives_is_refused() -> None:
    with pytest.raises(RetentionError, match="archived before"):
        RetentionPolicy("transcript", archive_after_days=90, grace_days=14, delete_after_days=30)

    for archive_days, grace_days in ((0, 1), (1, 0)):
        with pytest.raises(RetentionError, match="must be positive"):
            RetentionPolicy("transcript", archive_after_days=archive_days, grace_days=grace_days)
