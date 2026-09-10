"""One timeline over two tracks, and the labels that keep claims apart.

Who spoke is decided by which track the audio came from and by nothing else. The
microphone is the learner, the system track is whoever else was in the call. That is a
fact about wiring rather than a judgment about voices, which is exactly why speaker
diarization stays out of scope: guessing which of three remote voices said something is
a claim this system has no evidence for, and it would sit in the record looking like one
that does.

Questions are segmented the same way. A question is a stretch of remote speech, and the
answer is the learner's speech that follows it before the next one starts. Nothing here
tries to detect a question mark or a rising tone.

The four labels come from the analysis contract rather than a new vocabulary, so a claim
carries the same meaning here as it does everywhere downstream: what was said, what the
learner recalls, what was inferred, and what nobody knows. Uncertainty is the confidence
on the claim rather than a fifth label, because a thing can be observed and still be
hard to hear.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from tamforge_protocol.agents import AnalysisObservation

from ..speech.metrics.words import RecognizedWord

# Which track a stretch of speech came from. Not who, which input.
Speaker = Literal["user", "remote"]

# The same four the analysis contract uses. Adding a fifth here would mean a claim
# labelled one thing on this side and something else downstream.
ClaimLabel = Literal["observed_content", "user_stated", "inferred", "unknown"]

# A gap this long between remote words starts a new question rather than continuing one.
QUESTION_GAP_MS = 2_000


class TimelineError(ValueError):
    """A timeline that cannot be built from the two tracks as given."""


@dataclass(frozen=True, slots=True)
class Utterance:
    """One continuous stretch of speech on one track."""

    speaker: Speaker
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.end_ms < self.start_ms:
            raise TimelineError("an utterance cannot end before it starts")


@dataclass(frozen=True, slots=True)
class QuestionTurn:
    """One remote question and the learner's answer to it, by position in time."""

    index: int
    question: Utterance
    answer: Utterance | None

    @property
    def answered(self) -> bool:
        return self.answer is not None

    @property
    def response_latency_ms(self) -> int | None:
        if self.answer is None:
            return None
        return max(0, self.answer.start_ms - self.question.end_ms)


@dataclass(frozen=True, slots=True)
class Claim:
    """Something the record asserts, and how strongly, and on whose word."""

    statement: str
    label: ClaimLabel
    confidence: Decimal
    turn_index: int | None = None

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise TimelineError("a claim says something")
        if not Decimal(0) <= self.confidence <= Decimal(1):
            raise TimelineError("confidence runs from zero to one")


def _group(words: Sequence[RecognizedWord], speaker: Speaker, gap_ms: int) -> tuple[Utterance, ...]:
    if not words:
        return ()
    utterances: list[Utterance] = []
    start = words[0].start_ms
    end = words[0].end_ms
    for word in words[1:]:
        if word.start_ms - end >= gap_ms:
            utterances.append(Utterance(speaker, start, end))
            start = word.start_ms
        end = max(end, word.end_ms)
    utterances.append(Utterance(speaker, start, end))
    return tuple(utterances)


def build_timeline(
    *,
    microphone: Sequence[RecognizedWord],
    system_audio: Sequence[RecognizedWord],
    gap_ms: int = QUESTION_GAP_MS,
) -> tuple[Utterance, ...]:
    """Every stretch of speech from both tracks, in the order it happened."""
    if gap_ms < 1:
        raise TimelineError("a gap that starts a new utterance is at least one millisecond")
    merged = [*_group(microphone, "user", gap_ms), *_group(system_audio, "remote", gap_ms)]
    return tuple(sorted(merged, key=lambda item: (item.start_ms, item.speaker)))


def segment_questions(
    *,
    microphone: Sequence[RecognizedWord],
    system_audio: Sequence[RecognizedWord],
    gap_ms: int = QUESTION_GAP_MS,
) -> tuple[QuestionTurn, ...]:
    """Pair each remote utterance with the learner speech that answers it."""
    questions = _group(system_audio, "remote", gap_ms)
    answers = _group(microphone, "user", gap_ms)
    turns: list[QuestionTurn] = []
    for index, question in enumerate(questions):
        next_question = questions[index + 1].start_ms if index + 1 < len(questions) else None
        answer = next(
            (
                item
                for item in answers
                if item.start_ms >= question.end_ms
                and (next_question is None or item.start_ms < next_question)
            ),
            None,
        )
        turns.append(QuestionTurn(index=index, question=question, answer=answer))
    return tuple(turns)


def label_of(observation: AnalysisObservation) -> ClaimLabel:
    """Read an analysis observation's attribution as this module's label. Same values."""
    return observation.attribution


__all__ = [
    "QUESTION_GAP_MS",
    "Claim",
    "ClaimLabel",
    "QuestionTurn",
    "Speaker",
    "TimelineError",
    "Utterance",
    "build_timeline",
    "label_of",
    "segment_questions",
]
