"""Which interviews may name an opportunity, and which must not."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from tamforge_protocol.interviews import (
    OPPORTUNITY_LINKED_KINDS,
    Interview,
    InterviewError,
    RecordingPermission,
    artifact_key,
    in_scope,
    recording_lock,
    require_same_scope,
    require_unlocked,
    retrieve,
    scope_of,
    storage_prefix,
)

NOW = datetime(2026, 9, 12, 15, tzinfo=UTC)


def interview(**overrides: object) -> Interview:
    data: dict[str, object] = {
        "interview_id": 11,
        "owner_id": 1,
        "kind": "real",
        "scheduled_for": NOW,
        "opportunity_id": 4,
        "stage_label": "Technical panel",
    }
    data.update(overrides)
    return Interview.model_validate(data)


def test_a_real_interview_names_the_opportunity_it_belongs_to() -> None:
    real = interview()

    assert real.is_real is True
    assert real.opportunity_id == 4
    assert OPPORTUNITY_LINKED_KINDS == frozenset({"real"})


def test_a_real_interview_without_an_opportunity_is_untraceable_and_refused() -> None:
    with pytest.raises(ValidationError, match="only a real interview"):
        interview(opportunity_id=None, stage_label=None)


@pytest.mark.parametrize("kind", ["practice", "mock"])
def test_an_exercise_never_names_a_live_opportunity(kind: str) -> None:
    # An exercise linked to a live opportunity is how practice material ends up read
    # as if it were the real conversation.
    assert interview(kind=kind, opportunity_id=None, stage_label=None).is_real is False

    with pytest.raises(ValidationError, match="only a real interview"):
        interview(kind=kind)


@pytest.mark.parametrize("kind", ["practice", "mock"])
def test_an_exercise_has_no_stage_in_anyones_pipeline(kind: str) -> None:
    with pytest.raises(ValidationError):
        interview(kind=kind, opportunity_id=None, stage_label="Technical panel")


def test_a_naive_schedule_is_refused() -> None:
    with pytest.raises(ValidationError):
        interview(scheduled_for=datetime(2026, 9, 12, 15))


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        interview(kind="informal_chat")


# Issue #80: real-interview recording stays locked until permission is attested, and
# revocation or a missing scope stops both capture and processing.
LATER = datetime(2026, 9, 12, 16, tzinfo=UTC)


def permission(**overrides: object) -> RecordingPermission:
    data: dict[str, object] = {
        "interview_id": 11,
        "attested_by": "Interviewer, Northwind",
        "attested_at": NOW,
        "scopes": ("record_audio", "store_transcript"),
    }
    data.update(overrides)
    return RecordingPermission.model_validate(data)


def test_an_attested_permission_opens_exactly_the_scopes_it_named() -> None:
    granted = permission()

    assert recording_lock(interview(), granted, scope="record_audio", now=LATER) == (
        "unlocked",
        "none",
    )
    assert recording_lock(interview(), granted, scope="release_to_claude", now=LATER) == (
        "locked",
        "scope_not_granted",
    )


def test_recording_is_locked_until_somebody_attests() -> None:
    assert recording_lock(interview(), None, scope="record_audio", now=LATER) == (
        "locked",
        "permission_missing",
    )


def test_a_permission_for_another_interview_unlocks_nothing() -> None:
    assert recording_lock(
        interview(), permission(interview_id=99), scope="record_audio", now=LATER
    ) == ("locked", "permission_missing")


def test_revocation_stops_capture_and_processing_alike() -> None:
    # Withdrawing consent has to change what happens to material already recorded, or
    # withdrawing it changes nothing that already happened.
    revoked = permission(revoked_at=LATER)

    for scope in ("record_audio", "store_transcript"):
        assert recording_lock(interview(), revoked, scope=scope, now=LATER) == (
            "locked",
            "permission_revoked",
        )
    assert recording_lock(interview(), revoked, scope="record_audio", now=NOW)[0] == "unlocked"


@pytest.mark.parametrize("kind", ["practice", "mock"])
def test_an_exercise_reports_not_applicable_rather_than_unlocked(kind: str) -> None:
    exercise = interview(kind=kind, opportunity_id=None, stage_label=None)

    assert recording_lock(exercise, permission(), scope="record_audio", now=LATER) == (
        "locked",
        "not_applicable",
    )


def test_requiring_an_unlocked_scope_raises_with_the_rule_that_closed_it() -> None:
    with pytest.raises(InterviewError, match="permission_missing"):
        require_unlocked(interview(), None, scope="record_audio", now=LATER)
    with pytest.raises(InterviewError, match="scope_not_granted"):
        require_unlocked(interview(), permission(), scope="release_to_claude", now=LATER)

    assert require_unlocked(interview(), permission(), scope="record_audio", now=LATER) is None


def test_a_permission_names_who_gave_it_and_what_it_covers() -> None:
    with pytest.raises(ValidationError):
        permission(attested_by="   ")
    with pytest.raises(ValidationError):
        permission(scopes=())
    with pytest.raises(ValidationError, match="granted once"):
        permission(scopes=("record_audio", "record_audio"))


def test_permission_cannot_be_revoked_before_it_was_given() -> None:
    with pytest.raises(ValidationError, match="revoked before"):
        permission(revoked_at=datetime(2026, 9, 11, 15, tzinfo=UTC))


def test_naive_timestamps_are_refused_on_every_side() -> None:
    with pytest.raises(ValidationError):
        permission(attested_at=datetime(2026, 9, 12, 16))
    with pytest.raises(InterviewError, match="timezone-aware"):
        recording_lock(
            interview(), permission(), scope="record_audio", now=datetime(2026, 9, 12, 16)
        )


# Issue #81: practice and real-interview artifacts use separate sensitivity scopes,
# storage prefixes and retrieval filters, so neither enters the other's context.


def test_the_kind_of_interview_decides_the_scope_and_nothing_else() -> None:
    assert scope_of(interview()) == "real_interview"
    for kind in ("practice", "mock"):
        exercise = interview(kind=kind, opportunity_id=None, stage_label=None)
        assert scope_of(exercise) == "practice"


def test_the_two_scopes_have_prefixes_that_cannot_nest() -> None:
    practice = storage_prefix("practice")
    real = storage_prefix("real_interview")

    assert practice != real
    # Neither is a prefix of the other, so a prefix match cannot walk from one into the
    # other however the keys are built.
    assert not practice.startswith(real)
    assert not real.startswith(practice)


def test_an_artifact_key_carries_the_scope_it_belongs_to() -> None:
    real_key = artifact_key(interview(), artifact_id="transcript")
    practice_key = artifact_key(
        interview(kind="practice", opportunity_id=None, stage_label=None), artifact_id="transcript"
    )

    assert real_key.startswith(storage_prefix("real_interview"))
    assert practice_key.startswith(storage_prefix("practice"))
    assert real_key != practice_key


def test_a_retrieval_returns_only_the_scope_it_asked_for() -> None:
    keys = [
        artifact_key(interview(), artifact_id="transcript"),
        artifact_key(
            interview(interview_id=12, kind="practice", opportunity_id=None, stage_label=None),
            artifact_id="transcript",
        ),
    ]

    assert retrieve(keys, scope="real_interview") == (keys[0],)
    assert retrieve(keys, scope="practice") == (keys[1],)


def test_a_retrieval_has_to_say_which_world_it_wants() -> None:
    # The one that does not say is the one that eventually reads from both.
    with pytest.raises(TypeError):
        retrieve([])  # type: ignore[call-arg]


def test_in_scope_answers_for_one_key_the_same_way_retrieval_does() -> None:
    real_key = artifact_key(interview(), artifact_id="transcript")

    assert in_scope(real_key, scope="real_interview") is True
    assert in_scope(real_key, scope="practice") is False


def test_material_from_the_two_worlds_never_shares_a_context() -> None:
    real = interview()
    practice = interview(interview_id=12, kind="practice", opportunity_id=None, stage_label=None)

    assert require_same_scope(real, interview(interview_id=13)) is None
    with pytest.raises(InterviewError, match="do not mix"):
        require_same_scope(real, practice)


def test_an_artifact_id_cannot_climb_out_of_its_prefix() -> None:
    for bad in ("", "   ", "../real/11/transcript", "nested/id"):
        with pytest.raises(InterviewError, match="single non-empty segment"):
            artifact_key(interview(), artifact_id=bad)


def test_an_unknown_scope_is_refused_rather_than_guessed() -> None:
    with pytest.raises(InterviewError, match="unknown sensitivity scope"):
        storage_prefix("everything")  # type: ignore[arg-type]
