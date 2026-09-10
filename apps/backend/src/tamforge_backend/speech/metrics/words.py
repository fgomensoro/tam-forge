"""Group whisper tokens back into the words every version-1 metric counts.

`schemas.TranscriptWord` is one whisper BPE token, not one English word: sub-word
pieces and punctuation each arrive as their own entry, and `WhisperTranscriber`
preserves the leading space that marks a word-initial token. Counting entries would
report roughly 1.3 words for every word actually spoken, so every calculator here
consumes `segment_words` output rather than the raw entries.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import TranscriptSubmitCommand, TranscriptWord

# Kept inside a word rather than treated as a boundary: contractions and hyphenated
# compounds are one word, and whisper emits both characters mid-token.
_WORD_INNER = "'’-"


@dataclass(frozen=True, slots=True)
class RecognizedWord:
    """One spoken word, casefolded, spanning every token that composes it."""

    text: str
    start_ms: int
    end_ms: int


def _normalize(text: str) -> str:
    kept = "".join(char for char in text.casefold() if char.isalnum() or char in _WORD_INNER)
    return kept.strip(_WORD_INNER)


def segment_words(transcript: TranscriptSubmitCommand) -> tuple[RecognizedWord, ...]:
    """Return the recognized words of a transcript in order, dropping pure punctuation."""
    groups: list[list[TranscriptWord]] = []
    for segment in transcript.segments:
        for token in segment.words:
            if groups and not token.text[:1].isspace():
                groups[-1].append(token)
            else:
                groups.append([token])
    words = []
    for group in groups:
        text = _normalize("".join(token.text for token in group))
        if not text:
            continue
        words.append(
            RecognizedWord(text=text, start_ms=group[0].start_ms, end_ms=group[-1].end_ms)
        )
    return tuple(words)


def token_count(transcript: TranscriptSubmitCommand) -> int:
    return sum(len(segment.words) for segment in transcript.segments)


__all__ = ["RecognizedWord", "segment_words", "token_count"]
