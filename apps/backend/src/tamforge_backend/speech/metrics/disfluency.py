"""Version-1 filler and restart counting over recognized words.

Off-the-shelf whisper transcribes for readability and drops many disfluencies, so
every count here is a floor rather than a total and is published as
`detected_minimum`. Version 1 also stays with unambiguous hesitations and hedges:
`like`, `so`, `well` and `right` carry meaning as often as they stall, and counting
them would inflate a number nobody can audit back to the audio.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .models import FILLER_LEXICON_VERSION, MeasuredMetric, Metric, UnavailableMetric
from .words import RecognizedWord

FILLERS: frozenset[str] = frozenset(
    {"uh", "uhh", "uhm", "um", "umm", "er", "erm", "ah", "eh", "hm", "hmm", "mm", "mhm", "huh"}
)
HEDGES: frozenset[tuple[str, str]] = frozenset(
    {("you", "know"), ("i", "mean"), ("sort", "of"), ("kind", "of")}
)


@dataclass(frozen=True, slots=True)
class DisfluencyMetrics:
    filler_count: Metric
    restart_count: Metric
    filler_lexicon_version: str = FILLER_LEXICON_VERSION


def _detected(name: str, count: int) -> MeasuredMetric:
    return MeasuredMetric(
        name=name, unit="count", value=Decimal(count), measurement_status="detected_minimum"
    )


def _count_fillers(texts: Sequence[str]) -> int:
    count = 0
    index = 0
    while index < len(texts):
        if (texts[index], texts[index + 1] if index + 1 < len(texts) else "") in HEDGES:
            count += 1
            index += 2
            continue
        if texts[index] in FILLERS:
            count += 1
        index += 1
    return count


def calculate_disfluency(words: Sequence[RecognizedWord]) -> DisfluencyMetrics:
    """Return the version-1 filler and restart floors, or their unavailable reason."""
    if not words:
        return DisfluencyMetrics(
            filler_count=UnavailableMetric(
                name="filler_count", unit="count", reason_code="no_recognized_words"
            ),
            restart_count=UnavailableMetric(
                name="restart_count", unit="count", reason_code="no_recognized_words"
            ),
        )

    texts = [word.text for word in words]
    restarts = sum(
        1 for earlier, later in zip(texts, texts[1:], strict=False) if earlier == later
    )
    return DisfluencyMetrics(
        filler_count=_detected("filler_count", _count_fillers(texts)),
        restart_count=_detected("restart_count", restarts),
    )


__all__ = ["FILLERS", "HEDGES", "DisfluencyMetrics", "calculate_disfluency"]
