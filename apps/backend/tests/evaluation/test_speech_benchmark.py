"""The private voice gold set: consented, adjudicated, and never committed as audio."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from tamforge_backend.speech.evaluation import (
    CONDITIONS,
    GoldSetError,
    GoldSetManifest,
    GoldSetSummary,
    adjudicated_reference,
    assert_no_raw_audio_committed,
    summarize,
)
from tamforge_backend.speech.evaluation.goldset import reference_tokens

CONSENTED = datetime(2026, 9, 1, 12, tzinfo=UTC)
DECIDED = datetime(2026, 9, 5, 9, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64


def recording(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "recording_id": "quiet-01",
        "condition": "quiet",
        "private_path": "apps/macos/PrivateAudio/gold/quiet-01.wav",
        "audio_sha256": SHA_A,
        "audio_bytes": 480_000,
        "duration_ms": 5_000,
        "reference": [
            {"text": "the", "start_ms": 0, "end_ms": 200},
            {"text": "total", "start_ms": 250, "end_ms": 600},
            {"text": "addressable", "start_ms": 620, "end_ms": 1_300},
            {"text": "market", "start_ms": 1_320, "end_ms": 1_800},
        ],
        "adjudications": [],
    }
    data.update(overrides)
    return data


def manifest(**overrides: object) -> GoldSetManifest:
    data: dict[str, object] = {
        "consent": {
            "speaker_alias": "speaker-1",
            "consented_at": CONSENTED.isoformat(),
            "purpose": "private_speech_benchmark",
        },
        "critical_terms": ["total addressable market", "churn"],
        "recordings": [recording()],
    }
    data.update(overrides)
    return GoldSetManifest.model_validate(data)


def adjudication(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "word_index": 1,
        "listened_by": "frank",
        "decided_at": DECIDED.isoformat(),
        "heard": "totally",
        "reason": "script_deviation",
    }
    data.update(overrides)
    return data


# --- consent and privacy -----------------------------------------------------------------


def test_a_gold_set_names_a_consenting_speaker_by_alias_only() -> None:
    m = manifest()
    assert m.consent.speaker_alias == "speaker-1" and m.consent.revocable is True
    with pytest.raises(ValidationError):
        manifest(
            consent={
                "speaker_alias": "Francisco Gomensoro",
                "consented_at": CONSENTED.isoformat(),
                "purpose": "private_speech_benchmark",
            }
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        manifest(
            consent={
                "speaker_alias": "speaker-1",
                "consented_at": "2026-09-01T12:00:00",
                "purpose": "private_speech_benchmark",
            }
        )


@pytest.mark.parametrize(
    "path",
    [
        "docs/project/quiet-01.wav",
        "/Users/frank/quiet-01.wav",
        "apps/macos/PrivateAudio/../Resources/quiet-01.wav",
        "apps/macos/PrivateAudio/gold/quiet-01.txt",
    ],
)
def test_audio_lives_only_under_the_private_root(path: str) -> None:
    with pytest.raises(ValidationError):
        manifest(recordings=[recording(private_path=path)])


def test_tracked_audio_is_refused_even_when_the_manifest_does_not_name_it() -> None:
    m = manifest()
    assert_no_raw_audio_committed(["docs/project/model-benchmark-v1.json"], m)
    with pytest.raises(GoldSetError, match="raw audio is tracked"):
        assert_no_raw_audio_committed(["apps/macos/PrivateAudio/gold/quiet-01.wav"], m)
    with pytest.raises(GoldSetError, match="under the private root"):
        assert_no_raw_audio_committed(["apps/macos/PrivateAudio/other/take.m4a"], m)


# --- reference words and timestamps ------------------------------------------------------


def test_reference_words_keep_their_timestamps_in_order() -> None:
    words = manifest().recordings[0].reference
    assert [w.text for w in words] == ["the", "total", "addressable", "market"]
    assert [(w.start_ms, w.end_ms) for w in words][:2] == [(0, 200), (250, 600)]


def test_a_reference_that_overlaps_runs_backwards_or_outlives_the_audio_is_refused() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        manifest(
            recordings=[
                recording(
                    reference=[
                        {"text": "a", "start_ms": 0, "end_ms": 500},
                        {"text": "b", "start_ms": 400, "end_ms": 900},
                    ]
                )
            ]
        )
    with pytest.raises(ValidationError, match="ends after it starts"):
        manifest(recordings=[recording(reference=[{"text": "a", "start_ms": 500, "end_ms": 100}])])
    with pytest.raises(ValidationError, match="after the recording"):
        manifest(recordings=[recording(reference=[{"text": "a", "start_ms": 0, "end_ms": 9_000}])])
    with pytest.raises(ValidationError, match="cannot be scored"):
        manifest(recordings=[recording(reference=[])])


# --- adjudication --------------------------------------------------------------------------


def test_an_adjudication_is_applied_on_top_of_the_reference_not_edited_into_it() -> None:
    rec = manifest(recordings=[recording(adjudications=[adjudication()])]).recordings[0]
    assert rec.reference[1].text == "total"
    applied = adjudicated_reference(rec)
    assert applied[1].text == "totally" and (applied[1].start_ms, applied[1].end_ms) == (250, 600)
    assert reference_tokens(rec) == ("the", "totally", "addressable", "market")


def test_the_latest_decision_on_a_word_wins() -> None:
    later = adjudication(
        listened_by="reviewer-2",
        decided_at=(DECIDED + timedelta(days=1)).isoformat(),
        heard="total",
    )
    rec = manifest(recordings=[recording(adjudications=[adjudication(), later])]).recordings[0]
    assert adjudicated_reference(rec)[1].text == "total"


def test_an_adjudication_must_point_at_a_word_and_a_person_decides_a_word_once() -> None:
    with pytest.raises(ValidationError, match="does not exist"):
        manifest(recordings=[recording(adjudications=[adjudication(word_index=9)])])
    with pytest.raises(ValidationError, match="one word once"):
        manifest(
            recordings=[recording(adjudications=[adjudication(), adjudication(heard="totals")])]
        )


def test_an_adjudication_cannot_predate_consent() -> None:
    early = adjudication(decided_at=(CONSENTED - timedelta(hours=1)).isoformat())
    with pytest.raises(ValidationError, match="predate the consent"):
        manifest(recordings=[recording(adjudications=[early])])


def test_adjudication_reasons_are_a_closed_vocabulary() -> None:
    with pytest.raises(ValidationError):
        manifest(recordings=[recording(adjudications=[adjudication(reason="vibes")])])


# --- the set as a whole and its committed summary -------------------------------------------


def test_recordings_are_distinct_by_id_and_by_audio() -> None:
    with pytest.raises(ValidationError, match="ids repeat"):
        manifest(recordings=[recording(), recording(audio_sha256=SHA_B)])
    with pytest.raises(ValidationError, match="same audio"):
        manifest(recordings=[recording(), recording(recording_id="quiet-02")])


def test_the_summary_counts_conditions_words_and_adjudicators_and_names_no_words() -> None:
    m = manifest(
        recordings=[
            recording(adjudications=[adjudication(), adjudication(word_index=3, heard="markets")]),
            recording(
                recording_id="noise-01",
                condition="room_noise",
                audio_sha256=SHA_B,
                duration_ms=7_000,
            ),
        ]
    )
    summary = summarize(m)

    assert isinstance(summary, GoldSetSummary)
    assert summary.recordings == 2 and summary.total_duration_ms == 12_000
    assert (
        summary.recordings_per_condition["quiet"] == 1
        and summary.recordings_per_condition["fast"] == 0
    )
    assert summary.missing_conditions == tuple(
        c for c in CONDITIONS if c not in {"quiet", "room_noise"}
    )
    assert (summary.reference_words, summary.adjudicated_words, summary.adjudicators) == (8, 2, 1)
    assert summary.audio_sha256 == (SHA_A, SHA_B)
    text = summary.render()
    for forbidden in ("addressable", "totally", "PrivateAudio", "start_ms", "frank"):
        assert forbidden not in text
    assert '"speaker_alias": "speaker-1"' in text


def test_the_summary_is_a_strict_shape_a_reader_cannot_widen() -> None:
    with pytest.raises(ValidationError):
        GoldSetSummary.model_validate(
            {**summarize(manifest()).model_dump(), "transcript": "the total"}
        )
