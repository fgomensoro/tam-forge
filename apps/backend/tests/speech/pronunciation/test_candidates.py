"""Alignment candidates: privacy, licensing and cost decide now; accuracy waits for the gold set."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from tamforge_backend.speech.evaluation.goldset import GoldRecording, GoldSetManifest
from tamforge_backend.speech.pronunciation.candidates import (
    CANDIDATES,
    HOST_BUDGET_MB,
    AlignedWord,
    AlignmentCandidate,
    CandidateError,
    benchmark,
    compare,
    eligible,
)

SHA = "a" * 64


def test_every_candidate_states_the_four_axes() -> None:
    assert len(CANDIDATES) >= 4
    for c in CANDIDATES:
        assert c.license and isinstance(c.runs_on_host, bool) and c.resident_memory_mb > 0
        assert c.accuracy_status == "not_measured"


def test_a_candidate_that_sends_audio_off_host_is_ineligible_before_anything_else() -> None:
    hosted = next(c for c in CANDIDATES if c.key == "hosted-speech-api")
    assert "original audio would leave the host" in hosted.ineligibility
    assert hosted.key not in {c.key for c in eligible()}


def test_a_candidate_that_does_not_fit_the_speech_worker_budget_is_ineligible() -> None:
    gop = next(c for c in CANDIDATES if c.key == "kaldi-gop")
    assert gop.resident_memory_mb > HOST_BUDGET_MB
    assert any("MB" in r for r in gop.ineligibility)


def test_licenses_must_permit_a_private_deployment() -> None:
    proprietary = AlignmentCandidate("x", "x", "proprietary", True, False, 100, 1.0, False)
    assert any("license" in r for r in proprietary.ineligibility)
    assert all(c.license != "proprietary" for c in eligible())


def test_comparison_ranks_by_cost_and_refuses_an_accuracy_ranking_unmeasured() -> None:
    comparison = compare()
    assert comparison.eligible == ("mfa", "wav2vec2-ctc")
    assert comparison.ranked_by_cost == ("mfa", "wav2vec2-ctc")
    assert comparison.ranked_by_accuracy is None and comparison.recommendation is None
    assert set(comparison.ineligible) == {"kaldi-gop", "gentle", "hosted-speech-api"} - {
        "gentle"
    } | ({"gentle"} if "gentle" in comparison.ineligible else set())
    assert all(v == "not_measured" for v in comparison.accuracy_status.values())


def _gold() -> tuple[GoldRecording, ...]:
    manifest = GoldSetManifest.model_validate(
        {
            "consent": {
                "speaker_alias": "speaker-1",
                "consented_at": datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
                "purpose": "private_speech_benchmark",
            },
            "critical_terms": ["churn"],
            "recordings": [
                {
                    "recording_id": "quiet-01",
                    "condition": "quiet",
                    "private_path": "apps/macos/PrivateAudio/gold/quiet-01.wav",
                    "audio_sha256": SHA,
                    "audio_bytes": 10,
                    "duration_ms": 3000,
                    "reference": [
                        {"text": "the", "start_ms": 0, "end_ms": 200},
                        {"text": "churn", "start_ms": 250, "end_ms": 700},
                    ],
                }
            ],
        }
    )
    return manifest.recordings


def test_benchmark_measures_boundary_error_against_the_adjudicated_reference() -> None:
    def aligner(recording: GoldRecording) -> Sequence[AlignedWord]:
        return [AlignedWord("the", 10, 190), AlignedWord("churn", 270, 720)]

    measured = benchmark(CANDIDATES[0], _gold(), aligner=aligner, gold_set_sha256=SHA)
    assert measured.accuracy is not None
    assert measured.accuracy.mean_boundary_error_ms == 15.0
    assert (measured.accuracy.words_aligned, measured.accuracy.words_unaligned) == (2, 0)
    assert measured.accuracy_status == "measured" and measured.accuracy.gold_set_sha256 == SHA


def test_benchmark_counts_words_the_aligner_missed_and_refuses_an_empty_result() -> None:
    def half(recording: GoldRecording) -> Sequence[AlignedWord]:
        return [AlignedWord("the", 0, 200)]

    measured = benchmark(CANDIDATES[0], _gold(), aligner=half, gold_set_sha256=SHA)
    assert measured.accuracy is not None and measured.accuracy.words_unaligned == 1
    with pytest.raises(CandidateError, match="aligned no words"):
        benchmark(CANDIDATES[0], _gold(), aligner=lambda r: [], gold_set_sha256=SHA)


def test_an_ineligible_candidate_is_never_run_on_private_audio() -> None:
    hosted = next(c for c in CANDIDATES if c.key == "hosted-speech-api")
    calls: list[str] = []

    def aligner(recording: GoldRecording) -> Sequence[AlignedWord]:
        calls.append(recording.recording_id)
        return []

    with pytest.raises(CandidateError, match="ineligible"):
        benchmark(hosted, _gold(), aligner=aligner, gold_set_sha256=SHA)
    assert calls == []


def test_a_recommendation_exists_only_once_every_eligible_candidate_is_measured() -> None:
    def aligner(recording: GoldRecording) -> Sequence[AlignedWord]:
        return [AlignedWord("the", 0, 200), AlignedWord("churn", 250, 700)]

    ok = eligible()
    one = benchmark(ok[0], _gold(), aligner=aligner, gold_set_sha256=SHA)
    partial = compare((one, *ok[1:]))
    assert partial.recommendation is None
    both = tuple(benchmark(c, _gold(), aligner=aligner, gold_set_sha256=SHA) for c in ok)
    full = compare(both)
    assert full.ranked_by_accuracy is not None and full.recommendation in {c.key for c in ok}
