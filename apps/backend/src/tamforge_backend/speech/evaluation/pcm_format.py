"""PCM16 stays the recording format until a blinded evaluation says otherwise, in numbers.

48 kHz signed PCM16 is lossless, standard for speech, and about 1.04 GB per hour for a mono
microphone track plus a stereo system track. PCM24 costs half again as much disk, upload
and permanent storage. It replaces PCM16 only if a blinded gold-set evaluation shows a
meaningful gain in at least one primary outcome, critical-word recovery, alignment
reliability or human-rated intelligibility, larger than the measurement's own uncertainty.
A difference inside the uncertainty is inaudible waveform detail and does not justify the
cost. Without an evaluation at all, the answer is PCM16 and the decision says why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

PcmFormat = Literal["pcm_s16le", "pcm_s24le"]
Outcome = Literal["critical_word_recovery", "alignment_reliability", "human_intelligibility"]

DEFAULT_FORMAT: Final[PcmFormat] = "pcm_s16le"
# Bytes per hour for microphone mono plus system stereo at 48 kHz.
BYTES_PER_HOUR: Final[dict[PcmFormat, int]] = {
    "pcm_s16le": 48_000 * 2 * 3 * 3600,
    "pcm_s24le": 48_000 * 3 * 3 * 3600,
}
MAX_RECORDING_MINUTES: Final = 120
PER_RECORDING_CAP_BYTES: Final = int(2.5 * 1024**3)


class PcmDecisionError(ValueError):
    """An evaluation that cannot support a decision."""


@dataclass(frozen=True, slots=True)
class OutcomeMeasurement:
    outcome: Outcome
    pcm16: float
    pcm24: float
    uncertainty: float

    def __post_init__(self) -> None:
        if self.uncertainty < 0:
            raise PcmDecisionError("uncertainty is non-negative")

    @property
    def gain(self) -> float:
        return self.pcm24 - self.pcm16

    @property
    def material(self) -> bool:
        return self.gain > self.uncertainty


@dataclass(frozen=True, slots=True)
class BlindedEvaluation:
    gold_set_sha256: str
    blinded: bool
    measurements: tuple[OutcomeMeasurement, ...]

    def __post_init__(self) -> None:
        if not self.blinded:
            raise PcmDecisionError("only a blinded evaluation can change the format")
        if not self.measurements:
            raise PcmDecisionError("an evaluation measures at least one primary outcome")


@dataclass(frozen=True, slots=True)
class PcmDecision:
    chosen: PcmFormat
    reason: str
    material_outcomes: tuple[Outcome, ...]

    @property
    def extra_bytes_per_hour(self) -> int:
        return BYTES_PER_HOUR[self.chosen] - BYTES_PER_HOUR[DEFAULT_FORMAT]


def decide(evaluation: BlindedEvaluation | None) -> PcmDecision:
    if evaluation is None:
        return PcmDecision(DEFAULT_FORMAT, "no blinded evaluation exists; PCM16 is the default", ())
    material = tuple(m.outcome for m in evaluation.measurements if m.material)
    if material:
        gained = ", ".join(material)
        return PcmDecision(
            "pcm_s24le",
            f"gold set {evaluation.gold_set_sha256[:12]} gains past uncertainty in {gained}",
            material,
        )
    return PcmDecision(
        DEFAULT_FORMAT,
        f"blinded gold set {evaluation.gold_set_sha256[:12]}: no outcome gained beyond uncertainty",
        (),
    )


def fits_the_spool(*, minutes: int, fmt: PcmFormat) -> bool:
    """Whether a recording of this length fits the per-recording cap, overhead included."""
    return (
        minutes <= MAX_RECORDING_MINUTES
        and BYTES_PER_HOUR[fmt] * minutes / 60 * 1.05 <= PER_RECORDING_CAP_BYTES
    )


__all__ = [
    "BYTES_PER_HOUR",
    "DEFAULT_FORMAT",
    "MAX_RECORDING_MINUTES",
    "PER_RECORDING_CAP_BYTES",
    "BlindedEvaluation",
    "OutcomeMeasurement",
    "PcmDecision",
    "PcmDecisionError",
    "PcmFormat",
    "decide",
    "fits_the_spool",
]
