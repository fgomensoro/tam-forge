"""The debrief comes first, runs short, and never passes for anything else."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from tamforge_backend.interviews.policy import (
    DEBRIEF_MAX_MINUTES,
    DEBRIEF_WINDOW_MINUTES,
    Debrief,
    DebriefAttribution,
    DebriefError,
    require_debrief_before_release,
)
from tamforge_protocol.agents import AnalysisObservation

ENDED = datetime(2026, 9, 15, 16, tzinfo=UTC)


def debrief(**overrides: object) -> Debrief:
    data: dict[str, object] = {
        "interview_id": 11,
        "owner_id": 1,
        "interview_ended_at": ENDED,
        "committed_at": ENDED + timedelta(minutes=4),
        "minutes": 5,
        "notes": "The scaling question landed badly; I never named the trade-off.",
    }
    data.update(overrides)
    return Debrief(**data)  # type: ignore[arg-type]


def test_feedback_is_released_after_the_debrief_and_not_before() -> None:
    with pytest.raises(DebriefError, match="not before"):
        require_debrief_before_release(None, interview_id=11, owner_id=1)

    written = debrief()
    assert require_debrief_before_release(written, interview_id=11, owner_id=1) is written


def test_another_interviews_debrief_does_not_unlock_this_one() -> None:
    for changes in ({"interview_id": 12}, {"owner_id": 2}):
        with pytest.raises(DebriefError, match="another interview or owner"):
            require_debrief_before_release(debrief(**changes), interview_id=11, owner_id=1)


def test_a_debrief_is_a_memory_dump_not_an_essay() -> None:
    assert DEBRIEF_MAX_MINUTES == 5
    assert debrief(minutes=DEBRIEF_MAX_MINUTES).minutes == 5

    for minutes in (0, DEBRIEF_MAX_MINUTES + 1):
        with pytest.raises(DebriefError, match="1 to 5 minutes"):
            debrief(minutes=minutes)


def test_an_empty_debrief_is_not_a_debrief() -> None:
    with pytest.raises(DebriefError, match="empty debrief"):
        debrief(notes="   ")


def test_it_has_to_be_written_while_the_interview_is_still_fresh() -> None:
    assert DEBRIEF_WINDOW_MINUTES == 30
    assert debrief(committed_at=ENDED + timedelta(minutes=DEBRIEF_WINDOW_MINUTES))

    with pytest.raises(DebriefError, match="recollection"):
        debrief(committed_at=ENDED + timedelta(minutes=DEBRIEF_WINDOW_MINUTES, seconds=1))


def test_a_debrief_cannot_predate_the_interview_it_debriefs() -> None:
    with pytest.raises(DebriefError, match="after the interview"):
        debrief(committed_at=ENDED - timedelta(minutes=1))


def test_a_debrief_is_never_transcript_evidence_or_inference() -> None:
    # What the learner remembers, what the transcript shows and what a model concluded
    # are three different kinds of claim, and the difference does not survive being
    # flattened into one.
    assert get_args(DebriefAttribution) == ("user_stated",)
    assert debrief().attribution == "user_stated"
    assert debrief().is_transcript_evidence is False

    for other in ("observed_content", "inferred", "unknown"):
        with pytest.raises(TypeError):
            Debrief(  # type: ignore[call-arg]
                interview_id=11,
                owner_id=1,
                interview_ended_at=ENDED,
                committed_at=ENDED,
                minutes=5,
                notes="x",
                attribution=other,
                extra=1,
            )


def test_the_attribution_vocabulary_is_the_analysis_contracts_own() -> None:
    """The debrief's one value has to exist in the vocabulary a reviewer reads.

    If the two drifted, a debrief would arrive at the analysis layer as an attribution
    nothing there knows, and the safest thing that layer could do with it is guess.
    """
    reviewer_vocabulary = get_args(AnalysisObservation.model_fields["attribution"].annotation)

    assert set(get_args(DebriefAttribution)) <= set(reviewer_vocabulary)


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(DebriefError, match="timezone-aware"):
        debrief(committed_at=datetime(2026, 9, 15, 16, 4))


@pytest.mark.parametrize("field", ["interview_id", "owner_id"])
def test_a_debrief_names_its_interview_and_its_owner(field: str) -> None:
    with pytest.raises(DebriefError, match="names its interview"):
        debrief(**{field: 0})
