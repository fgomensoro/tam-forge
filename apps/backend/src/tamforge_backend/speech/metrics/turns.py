"""Response latency across the microphone and system-audio tracks of one recording.

Both tracks are derived from the same recording by the same deriver, so their word
timings share one clock. That is only true while the two derivation versions match,
which is why a mismatch reports `incompatible_timing_source` rather than subtracting
timestamps produced by two different pipelines.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .models import MeasuredMetric, Metric, UnavailableMetric
from .words import RecognizedWord

_NAME = "response_latency_ms"


def _unavailable(reason_code: str) -> UnavailableMetric:
    return UnavailableMetric(name=_NAME, unit="milliseconds", reason_code=reason_code)


def calculate_response_latency(
    *,
    microphone: Sequence[RecognizedWord],
    system_audio: Sequence[RecognizedWord] | None,
    microphone_derivation: str,
    system_audio_derivation: str | None,
) -> Metric:
    """Return the gap from the end of the prompt to the first user word."""
    if system_audio is None or system_audio_derivation is None:
        return _unavailable("system_track_unavailable")
    if system_audio_derivation != microphone_derivation:
        return _unavailable("incompatible_timing_source")
    if not system_audio:
        return _unavailable("no_prompt_speech")
    if not microphone:
        return _unavailable("no_user_speech")

    prompt_end_ms = system_audio[-1].end_ms
    first_user_ms = microphone[0].start_ms
    if first_user_ms < prompt_end_ms:
        # The user spoke over the prompt. There is no latency to report, and the
        # overlap itself belongs to a two-track timeline contract, not to this one.
        return _unavailable("overlapping_tracks")
    return MeasuredMetric(
        name=_NAME, unit="milliseconds", value=Decimal(first_user_ms - prompt_end_ms)
    )


__all__ = ["calculate_response_latency"]
