"""Private voice gold set: consented recordings, adjudicated references, aggregate summaries."""

from __future__ import annotations

from .goldset import (
    CONDITIONS,
    GOLD_SET_VERSION,
    PRIVATE_AUDIO_ROOT,
    Adjudication,
    Consent,
    GoldRecording,
    GoldSetError,
    GoldSetManifest,
    GoldSetSummary,
    ReferenceWord,
    adjudicated_reference,
    assert_no_raw_audio_committed,
    summarize,
)

__all__ = [
    "CONDITIONS",
    "GOLD_SET_VERSION",
    "PRIVATE_AUDIO_ROOT",
    "Adjudication",
    "Consent",
    "GoldRecording",
    "GoldSetError",
    "GoldSetManifest",
    "GoldSetSummary",
    "ReferenceWord",
    "adjudicated_reference",
    "assert_no_raw_audio_committed",
    "summarize",
]
