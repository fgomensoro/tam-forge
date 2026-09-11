"""Server-side pronunciation: candidate aligners, their benchmark, and a calibrated pipeline."""

from __future__ import annotations

from .candidates import (
    CANDIDATES,
    AlignmentCandidate,
    CandidateComparison,
    CandidateError,
    compare,
    eligible,
)
from .pipeline import (
    Calibration,
    PronunciationAssessment,
    PronunciationError,
    WordAssessment,
    assess,
)

__all__ = [
    "CANDIDATES",
    "AlignmentCandidate",
    "Calibration",
    "CandidateComparison",
    "CandidateError",
    "PronunciationAssessment",
    "PronunciationError",
    "WordAssessment",
    "assess",
    "compare",
    "eligible",
]
