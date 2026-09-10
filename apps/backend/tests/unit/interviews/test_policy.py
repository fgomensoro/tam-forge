"""The debrief comes first, runs short, and never passes for anything else."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_args

import pytest
from tamforge_backend.interviews import timeline as tl
from tamforge_backend.interviews.policy import (
    DEBRIEF_MAX_MINUTES,
    DEBRIEF_WINDOW_MINUTES,
    Debrief,
    DebriefAttribution,
    DebriefError,
    require_debrief_before_release,
)
from tamforge_backend.speech.metrics.words import RecognizedWord
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


# Issue #84: questions segmented from the two synchronized tracks, a timestamped
# user/remote timeline, labels kept apart, and no speaker diarization.

def words(*spans: tuple[int, int]) -> tuple[RecognizedWord, ...]:
    return tuple(
        RecognizedWord(text=f"w{index}", start_ms=start, end_ms=end)
        for index, (start, end) in enumerate(spans)
    )


def test_the_track_decides_the_speaker_and_nothing_else() -> None:
    built = tl.build_timeline(
        microphone=words((3_000, 3_500)), system_audio=words((0, 900))
    )

    assert [item.speaker for item in built] == ["remote", "user"]
    assert get_args(tl.Speaker) == ("user", "remote")


def test_the_timeline_runs_in_the_order_things_happened() -> None:
    built = tl.build_timeline(
        microphone=words((1_000, 1_400), (5_000, 5_400)),
        system_audio=words((0, 800), (3_000, 3_800)),
    )

    assert [item.start_ms for item in built] == [0, 1_000, 3_000, 5_000]
    assert [item.speaker for item in built] == ["remote", "user", "remote", "user"]


def test_a_long_silence_starts_a_new_utterance() -> None:
    assert tl.QUESTION_GAP_MS == 2_000
    joined = tl.build_timeline(
        microphone=words((0, 500), (1_000, 1_500)), system_audio=()
    )
    split = tl.build_timeline(
        microphone=words((0, 500), (3_000, 3_500)), system_audio=()
    )

    assert len(joined) == 1 and joined[0].end_ms == 1_500
    assert len(split) == 2


def test_each_question_takes_the_answer_that_follows_it() -> None:
    turns = tl.segment_questions(
        microphone=words((1_200, 2_000), (6_000, 7_000)),
        system_audio=words((0, 900), (4_500, 5_200)),
    )

    assert [turn.index for turn in turns] == [0, 1]
    assert turns[0].answer is not None and turns[0].answer.start_ms == 1_200
    assert turns[1].answer is not None and turns[1].answer.start_ms == 6_000
    assert turns[0].response_latency_ms == 300


def test_a_question_nobody_answered_is_recorded_as_unanswered() -> None:
    turns = tl.segment_questions(microphone=(), system_audio=words((0, 900)))

    assert turns[0].answered is False
    assert turns[0].answer is None
    assert turns[0].response_latency_ms is None


def test_speech_before_the_question_is_not_its_answer() -> None:
    turns = tl.segment_questions(
        microphone=words((0, 400)), system_audio=words((3_000, 3_800))
    )

    assert turns[0].answered is False


def test_there_is_no_place_to_record_which_remote_voice_spoke() -> None:
    # Guessing which of three remote voices said something is a claim this system has
    # no evidence for, and it would sit in the record looking like one that does.
    from dataclasses import fields

    names = {field.name for field in fields(tl.Utterance)}
    assert names == {"speaker", "start_ms", "end_ms"}
    for diarization in ("speaker_id", "voice_id", "participant", "diarization"):
        assert diarization not in names


def test_the_four_labels_are_the_analysis_contracts_own() -> None:
    # A fifth label here would mean a claim labelled one thing on this side and
    # something else downstream.
    reviewer = get_args(AnalysisObservation.model_fields["attribution"].annotation)

    assert get_args(tl.ClaimLabel) == reviewer
    assert set(reviewer) == {"observed_content", "user_stated", "inferred", "unknown"}


def test_uncertainty_rides_on_the_claim_rather_than_being_a_fifth_label() -> None:
    # A thing can be observed and still be hard to hear.
    claim = tl.Claim(statement="They said the renewal is at risk.", label="observed_content",
                     confidence=Decimal("0.4"))

    assert claim.label == "observed_content"
    assert claim.confidence == Decimal("0.4")

    for bad in (Decimal("-0.1"), Decimal("1.1")):
        with pytest.raises(tl.TimelineError, match="zero to one"):
            tl.Claim(statement="x", label="inferred", confidence=bad)


def test_an_empty_claim_says_nothing_and_is_refused() -> None:
    with pytest.raises(tl.TimelineError, match="says something"):
        tl.Claim(statement="   ", label="unknown", confidence=Decimal("0"))


def test_an_utterance_cannot_end_before_it_starts() -> None:
    with pytest.raises(tl.TimelineError, match="before it starts"):
        tl.Utterance("user", 900, 100)


def test_a_zero_gap_is_refused_rather_than_splitting_every_word() -> None:
    with pytest.raises(tl.TimelineError, match="at least one millisecond"):
        tl.build_timeline(microphone=words((0, 100)), system_audio=(), gap_ms=0)
