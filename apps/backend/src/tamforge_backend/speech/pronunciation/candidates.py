"""Which forced-alignment engine may score pronunciation, judged on four axes at once.

Accuracy is one axis and the one everyone asks about first, but it is the last one that
can be answered: it needs the private gold set recorded and adjudicated, and until that
run exists every candidate's accuracy is `not_measured` and no ranking may lean on it.
The other three axes are decided from facts that exist today. Privacy: the original
microphone audio never leaves the host, so a candidate that phones home is ineligible
before any other question. Licensing: the license must allow a private deployment on a
rented server without a per-seat fee. Cost: the CX23 has 3.8 GB of RAM shared with
PostgreSQL and Caddy, so a candidate's resident memory and CPU per audio minute are the
incremental cost, and a candidate that does not fit is ineligible too.

`compare` ranks only the eligible candidates and only on the axes that are measured; it
refuses to produce an accuracy ranking from unmeasured numbers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from statistics import mean
from typing import Final, Literal

from ..evaluation.goldset import GoldRecording, adjudicated_reference

License = Literal["MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "proprietary"]
PERMITTED_LICENSES: Final[frozenset[str]] = frozenset(
    {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0"}
)

# What the host can spare after PostgreSQL, Caddy and the other workers (host contract).
HOST_BUDGET_MB: Final = 768


class CandidateError(ValueError):
    """A comparison that would rank on something nobody measured."""


@dataclass(frozen=True, slots=True)
class AccuracyMeasurement:
    """Boundary error against adjudicated reference timestamps, on the private gold set."""

    gold_set_sha256: str
    recordings: int
    mean_boundary_error_ms: float
    words_aligned: int
    words_unaligned: int


@dataclass(frozen=True, slots=True)
class AlignmentCandidate:
    key: str
    name: str
    license: License
    runs_on_host: bool
    sends_audio_off_host: bool
    resident_memory_mb: int
    cpu_seconds_per_audio_minute: float
    produces_phone_scores: bool
    accuracy: AccuracyMeasurement | None = None

    @property
    def accuracy_status(self) -> Literal["measured", "not_measured"]:
        return "measured" if self.accuracy is not None else "not_measured"

    @property
    def ineligibility(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.runs_on_host or self.sends_audio_off_host:
            reasons.append("original audio would leave the host")
        if self.license not in PERMITTED_LICENSES:
            reasons.append(f"license {self.license} does not permit a private deployment")
        if self.resident_memory_mb > HOST_BUDGET_MB:
            reasons.append(
                f"needs {self.resident_memory_mb} MB, the speech worker has {HOST_BUDGET_MB} MB"
            )
        return tuple(reasons)


# Public facts about each candidate. Memory and CPU are the vendors' documented figures for
# CPU-only English alignment on a small model; they are inputs to eligibility, not accuracy.
CANDIDATES: Final[tuple[AlignmentCandidate, ...]] = (
    AlignmentCandidate(
        key="mfa",
        name="Montreal Forced Aligner (Kaldi, english_us_arpa)",
        license="MIT",
        runs_on_host=True,
        sends_audio_off_host=False,
        resident_memory_mb=600,
        cpu_seconds_per_audio_minute=8.0,
        produces_phone_scores=False,
    ),
    AlignmentCandidate(
        key="wav2vec2-ctc",
        name="wav2vec2 CTC forced alignment (torchaudio, WhisperX-style)",
        license="BSD-2-Clause",
        runs_on_host=True,
        sends_audio_off_host=False,
        resident_memory_mb=700,
        cpu_seconds_per_audio_minute=6.0,
        produces_phone_scores=False,
    ),
    AlignmentCandidate(
        key="kaldi-gop",
        name="Kaldi goodness-of-pronunciation (librispeech nnet3)",
        license="Apache-2.0",
        runs_on_host=True,
        sends_audio_off_host=False,
        resident_memory_mb=1200,
        cpu_seconds_per_audio_minute=12.0,
        produces_phone_scores=True,
    ),
    AlignmentCandidate(
        key="gentle",
        name="Gentle (Kaldi, unmaintained)",
        license="MIT",
        runs_on_host=True,
        sends_audio_off_host=False,
        resident_memory_mb=900,
        cpu_seconds_per_audio_minute=10.0,
        produces_phone_scores=False,
    ),
    AlignmentCandidate(
        key="hosted-speech-api",
        name="Hosted pronunciation assessment API",
        license="proprietary",
        runs_on_host=False,
        sends_audio_off_host=True,
        resident_memory_mb=50,
        cpu_seconds_per_audio_minute=0.1,
        produces_phone_scores=True,
    ),
)


def eligible(
    candidates: Sequence[AlignmentCandidate] = CANDIDATES,
) -> tuple[AlignmentCandidate, ...]:
    return tuple(c for c in candidates if not c.ineligibility)


@dataclass(frozen=True, slots=True)
class CandidateComparison:
    eligible: tuple[str, ...]
    ineligible: dict[str, tuple[str, ...]]
    ranked_by_cost: tuple[str, ...]
    ranked_by_accuracy: tuple[str, ...] | None
    accuracy_status: dict[str, str] = field(default_factory=dict)

    @property
    def recommendation(self) -> str | None:
        """Only once accuracy is measured for every eligible candidate; otherwise none."""
        return self.ranked_by_accuracy[0] if self.ranked_by_accuracy else None


def compare(candidates: Sequence[AlignmentCandidate] = CANDIDATES) -> CandidateComparison:
    ok = eligible(candidates)
    by_cost = tuple(
        c.key
        for c in sorted(ok, key=lambda c: (c.resident_memory_mb, c.cpu_seconds_per_audio_minute))
    )
    measured = [c for c in ok if c.accuracy is not None]
    ranked_by_accuracy: tuple[str, ...] | None = None
    if ok and len(measured) == len(ok):
        ranked_by_accuracy = tuple(
            c.key
            for c in sorted(
                measured,
                key=lambda c: (
                    c.accuracy.mean_boundary_error_ms if c.accuracy else 0.0,
                    c.resident_memory_mb,
                ),
            )
        )
    return CandidateComparison(
        eligible=tuple(c.key for c in ok),
        ineligible={c.key: c.ineligibility for c in candidates if c.ineligibility},
        ranked_by_cost=by_cost,
        ranked_by_accuracy=ranked_by_accuracy,
        accuracy_status={c.key: c.accuracy_status for c in candidates},
    )


@dataclass(frozen=True, slots=True)
class AlignedWord:
    text: str
    start_ms: int
    end_ms: int


Aligner = Callable[[GoldRecording], Sequence[AlignedWord]]
"""Runs one candidate over one gold recording's original audio and returns word boundaries."""


def benchmark(
    candidate: AlignmentCandidate,
    recordings: Sequence[GoldRecording],
    *,
    aligner: Aligner,
    gold_set_sha256: str,
) -> AlignmentCandidate:
    """Boundary error against the adjudicated reference; the candidate comes back with accuracy."""
    if candidate.ineligibility:
        raise CandidateError(
            f"{candidate.key} is ineligible; it is not benchmarked on private audio"
        )
    if not recordings:
        raise CandidateError("an empty gold set measures nothing")
    errors: list[float] = []
    aligned = 0
    unaligned = 0
    for recording in recordings:
        reference = adjudicated_reference(recording)
        hypothesis = {w.text.casefold(): w for w in aligner(recording)}
        for word in reference:
            found = hypothesis.get(word.text.casefold())
            if found is None:
                unaligned += 1
                continue
            aligned += 1
            errors.append(
                (abs(found.start_ms - word.start_ms) + abs(found.end_ms - word.end_ms)) / 2
            )
    if aligned == 0:
        raise CandidateError(f"{candidate.key} aligned no words; nothing to measure")
    measurement = AccuracyMeasurement(
        gold_set_sha256=gold_set_sha256,
        recordings=len(recordings),
        mean_boundary_error_ms=round(mean(errors), 3),
        words_aligned=aligned,
        words_unaligned=unaligned,
    )
    return AlignmentCandidate(
        key=candidate.key,
        name=candidate.name,
        license=candidate.license,
        runs_on_host=candidate.runs_on_host,
        sends_audio_off_host=candidate.sends_audio_off_host,
        resident_memory_mb=candidate.resident_memory_mb,
        cpu_seconds_per_audio_minute=candidate.cpu_seconds_per_audio_minute,
        produces_phone_scores=candidate.produces_phone_scores,
        accuracy=measurement,
    )


__all__ = [
    "CANDIDATES",
    "HOST_BUDGET_MB",
    "PERMITTED_LICENSES",
    "AccuracyMeasurement",
    "AlignedWord",
    "Aligner",
    "AlignmentCandidate",
    "CandidateComparison",
    "CandidateError",
    "benchmark",
    "compare",
    "eligible",
]
