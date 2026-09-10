"""Compose one versioned speech-metric report from a recording's persisted transcripts."""

from __future__ import annotations

from dataclasses import dataclass, fields
from uuid import UUID

from ..schemas import TranscriptSubmitCommand
from .disfluency import calculate_disfluency
from .fluency import calculate_fluency
from .models import (
    FILLER_LEXICON_VERSION,
    METRICS_VERSION,
    MetricEvidence,
    SpeechMetricsError,
    SpeechMetricsReport,
)
from .turns import calculate_response_latency
from .words import segment_words, token_count


@dataclass(frozen=True, slots=True)
class TranscriptSource:
    """A stored transcript and the identity a report cites it by."""

    transcript_id: int
    content_hash: str
    transcript: TranscriptSubmitCommand


def calculate_speech_metrics(
    *,
    recording_id: UUID,
    microphone: TranscriptSource,
    system_audio: TranscriptSource | None = None,
) -> SpeechMetricsReport:
    """Return every version-1 metric for one recording, measured or unavailable."""
    if microphone.transcript.track != "microphone":
        raise SpeechMetricsError("speaker metrics require the microphone track")
    if system_audio is not None and system_audio.transcript.track != "system_audio":
        raise SpeechMetricsError("prompt timing requires the system_audio track")

    words = segment_words(microphone.transcript)
    fluency = calculate_fluency(words)
    disfluency = calculate_disfluency(words)
    latency = calculate_response_latency(
        microphone=words,
        system_audio=segment_words(system_audio.transcript) if system_audio else None,
        microphone_derivation=microphone.transcript.derivation.derivation_version,
        system_audio_derivation=(
            system_audio.transcript.derivation.derivation_version if system_audio else None
        ),
    )
    evidence = MetricEvidence(
        metrics_version=METRICS_VERSION,
        filler_lexicon_version=FILLER_LEXICON_VERSION,
        recording_id=recording_id,
        microphone_transcript_id=microphone.transcript_id,
        microphone_content_hash=microphone.content_hash,
        derivation_version=microphone.transcript.derivation.derivation_version,
        model_sha256=microphone.transcript.model_identity.model_sha256,
        used_builtin_vad=microphone.transcript.model_identity.used_builtin_vad,
        token_count=token_count(microphone.transcript),
        recognized_word_count=len(words),
        system_audio_transcript_id=system_audio.transcript_id if system_audio else None,
        system_audio_content_hash=system_audio.content_hash if system_audio else None,
    )
    return SpeechMetricsReport(
        evidence=evidence,
        filler_count=disfluency.filler_count,
        restart_count=disfluency.restart_count,
        response_latency_ms=latency,
        **{field.name: getattr(fluency, field.name) for field in fields(fluency)},
    )


__all__ = ["TranscriptSource", "calculate_speech_metrics"]
