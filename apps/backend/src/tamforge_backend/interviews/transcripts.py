"""A pasted transcript, without audio, becomes speaker turns and a few honest counts.

There is no recording, so nothing here measures pronunciation, fluency, pace, pauses or
fillers; the analysis names what it left out so a later reader never mistakes it for a
recorded one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

TRANSCRIPT_ANALYSIS_VERSION: Final = "transcript-only-v1"
EXCLUDED_FINDINGS: Final[tuple[str, ...]] = (
    "pronunciation",
    "fluency",
    "pace",
    "pauses",
    "fillers",
)
DEFAULT_LEARNER_LABELS: Final[tuple[str, ...]] = ("frank", "me", "candidate", "fgomensoro")
SPEAKER_LINE = re.compile(
    r"^\s*(?:\[[^\]]{0,32}\]\s*)?([A-Za-z][A-Za-z0-9 .'_-]{0,40}?)\s*:\s*(.*)$"
)
MAX_TURNS = 5000

Speaker = Literal["learner", "other"]


@dataclass(frozen=True, slots=True)
class TranscriptTurn:
    speaker: Speaker
    label: str
    text: str

    def as_json(self) -> dict[str, object]:
        return {"speaker": self.speaker, "label": self.label, "text": self.text}


def parse_transcript_turns(
    text: str, learner_labels: tuple[str, ...] = DEFAULT_LEARNER_LABELS
) -> tuple[TranscriptTurn, ...]:
    """`Speaker: words` lines start a turn; unlabeled lines continue the previous one."""
    learners = {label.strip().casefold() for label in learner_labels if label.strip()}
    turns: list[TranscriptTurn] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = SPEAKER_LINE.match(line)
        if match is not None and match.group(2).strip():
            label = match.group(1).strip()
            speaker: Speaker = "learner" if label.casefold() in learners else "other"
            words = match.group(2).strip()
            if turns and turns[-1].label.casefold() == label.casefold():
                last = turns[-1]
                turns[-1] = TranscriptTurn(last.speaker, last.label, f"{last.text} {words}")
            else:
                turns.append(TranscriptTurn(speaker, label, words))
        elif turns:
            last = turns[-1]
            turns[-1] = TranscriptTurn(last.speaker, last.label, f"{last.text} {line}")
        if len(turns) >= MAX_TURNS:
            break
    return tuple(turns)


def transcript_metrics(turns: tuple[TranscriptTurn, ...]) -> dict[str, object]:
    """Counts a transcript supports: words and turns per side, and the learner's share."""
    learner_words = sum(len(t.text.split()) for t in turns if t.speaker == "learner")
    other_words = sum(len(t.text.split()) for t in turns if t.speaker == "other")
    total = learner_words + other_words
    learner_turns = sum(1 for t in turns if t.speaker == "learner")
    longest = max((len(t.text.split()) for t in turns if t.speaker == "learner"), default=0)
    return {
        "learner_words": learner_words,
        "other_words": other_words,
        "learner_turns": learner_turns,
        "other_turns": len(turns) - learner_turns,
        "learner_word_share": round(learner_words / total, 3) if total else 0.0,
        "longest_learner_turn_words": longest,
        "excluded_findings": list(EXCLUDED_FINDINGS),
    }


__all__ = [
    "DEFAULT_LEARNER_LABELS",
    "EXCLUDED_FINDINGS",
    "TRANSCRIPT_ANALYSIS_VERSION",
    "TranscriptTurn",
    "parse_transcript_turns",
    "transcript_metrics",
]
