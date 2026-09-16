"""Turns interleave both tracks by time; the metrics render as numbers or reason codes."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from tamforge_backend.speech.analysis import build_turns, metrics_json
from tamforge_backend.speech.metrics.models import MeasuredMetric, UnavailableMetric
from tamforge_backend.speech.schemas import TranscriptSubmitCommand


def _transcript(track: str, segments: list[tuple[int, int, str]]) -> TranscriptSubmitCommand:
    return TranscriptSubmitCommand.model_validate(
        {
            "schema_version": 1,
            "track": track,
            "segments": [
                {
                    "text": text,
                    "start_ms": start,
                    "end_ms": end,
                    "words": [{"text": text, "start_ms": start, "end_ms": end, "probability": 0.9}],
                }
                for start, end, text in segments
            ],
            "model_identity": {
                "runtime_version": "b4938",
                "model_filename": "ggml-small.en-q5_1.bin",
                "model_sha256": "a" * 64,
                "metal_requested": True,
                "used_builtin_vad": False,
                "language": "en",
            },
            "derivation": {
                "derivation_version": "tamforge-asr16k-v1",
                "source_sample_rate": 48_000,
                "source_channel_count": 1,
                "source_sample_count": 480_000,
                "output_sample_rate": 16_000,
                "output_sample_count": 160_000,
                "zero_filled_gaps": [],
                "source_pcm_sha256": "b" * 64,
                "derived_pcm_sha256": "c" * 64,
                "quality": {
                    "version": "v1",
                    "sample_rate": 48_000,
                    "channel_count": 1,
                    "source_sample_count": 480_000,
                    "duration_seconds": 10.0,
                    "peak_absolute": 12_345,
                    "all_silence": False,
                    "clipped_ratio": 0.0,
                    "dc_offset": 0.0,
                    "channel_imbalance_decibels": None,
                    "discontinuity_count": 0,
                    "unavailable_dimensions": [],
                },
            },
        }
    )


def test_turns_interleave_the_two_tracks_by_start_time_and_label_the_speakers() -> None:
    microphone = _transcript(
        "microphone", [(2_000, 3_000, "I would start"), (3_200, 4_000, "with the logs")]
    )
    system = _transcript("system_audio", [(0, 1_500, "How would you debug it?")])

    turns = build_turns(microphone, system)

    assert [(t.speaker, t.start_ms, t.end_ms, t.text) for t in turns] == [
        ("other", 0, 1_500, "How would you debug it?"),
        ("learner", 2_000, 4_000, "I would start with the logs"),
    ]


def test_a_long_pause_splits_a_speaker_into_two_turns_and_blank_segments_are_dropped() -> None:
    microphone = _transcript(
        "microphone", [(0, 1_000, "First thought"), (1_500, 1_600, "   "), (5_000, 6_000, "Second")]
    )

    turns = build_turns(microphone, None)

    assert [t.text for t in turns] == ["First thought", "Second"]
    assert turns[0].as_json() == {
        "speaker": "learner",
        "start_ms": 0,
        "end_ms": 1_000,
        "text": "First thought",
    }


def test_metrics_render_measured_values_as_numbers_and_the_rest_as_reason_codes() -> None:
    names = (
        "response_duration_seconds",
        "speech_rate_wpm",
        "articulation_rate_wpm",
        "phonation_time_ratio",
        "mean_length_of_run",
        "pause_count_250_499_ms",
        "pause_count_500_999_ms",
        "pause_count_1000_ms_plus",
        "pause_seconds_total",
        "filler_count",
        "restart_count",
        "response_latency_ms",
    )
    report = SimpleNamespace(
        **{
            name: MeasuredMetric(name=name, unit="count", value=Decimal("2"))
            for name in names
            if name != "response_latency_ms"
        },
        response_latency_ms=UnavailableMetric(
            name="response_latency_ms", unit="milliseconds", reason_code="no_prompt_speech"
        ),
    )
    report.speech_rate_wpm = MeasuredMetric(
        name="speech_rate_wpm", unit="wpm", value=Decimal("142.5")
    )

    rendered = metrics_json(report)

    assert rendered["filler_count"] == 2 and isinstance(rendered["filler_count"], int)
    assert rendered["speech_rate_wpm"] == 142.5
    assert rendered["response_latency_ms"] == {"unavailable": "no_prompt_speech"}
