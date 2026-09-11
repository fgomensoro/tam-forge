"""The private voice gold set, and what may and may not leave the machine it lives on.

Model selection rests on one person's voice, recorded with their consent across the
conditions an interview actually has: a quiet room, a noisy one, fast answers, long
pauses, non-native pronunciation, and the TAM vocabulary that a generic model tends to
mangle. That audio is private. It never enters the repository, and neither does the
manifest that describes it, because a manifest with reference words and timestamps is a
transcript of the speaker.

What the manifest holds is the ground truth a benchmark is scored against: for every
recording, the words the speaker actually said with the moment each one starts and ends,
and the adjudications that turned a script into what was really said. An adjudication is
a person listening and deciding, with their name and the moment kept, and it is applied
on top of the reference rather than edited into it, so the script and every correction
stay readable.

The only thing that is ever committed is a summary: counts per condition, how many words
were adjudicated and by how many people, and the hashes that tie the summary to the audio
it describes. No words, no times, no paths.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

GOLD_SET_VERSION: Final = "voice-gold-set-v1"

# Where the audio and the manifest live. Gitignored, and enforced here rather than trusted.
PRIVATE_AUDIO_ROOT: Final = PurePosixPath("apps/macos/PrivateAudio")
AUDIO_SUFFIXES: Final[frozenset[str]] = frozenset({".wav", ".m4a", ".caf", ".aiff", ".flac"})

Condition = Literal["quiet", "room_noise", "fast", "pauses", "non_native", "tam_terminology"]
CONDITIONS: Final[tuple[Condition, ...]] = (
    "quiet",
    "room_noise",
    "fast",
    "pauses",
    "non_native",
    "tam_terminology",
)

AdjudicationReason = Literal[
    "mishearing", "script_deviation", "disfluency", "proper_noun", "number_format"
]

Sha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Token = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=64, pattern=r"^\S+$")
]
# A critical term may be a phrase ("total addressable market"); single spaces only.
Term = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=96, pattern=r"^\S+( \S+)*$")
]
Alias = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
]
Milliseconds = Annotated[int, Field(strict=True, ge=0)]


class GoldSetError(ValueError):
    """A manifest that would leak, contradict itself, or score against nothing."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Consent(_StrictModel):
    """One speaker, identified by an alias, agreeing to be recorded for this purpose."""

    speaker_alias: Alias
    consented_at: datetime
    purpose: Literal["private_speech_benchmark"]
    revocable: Literal[True] = True

    @model_validator(mode="after")
    def _aware(self) -> Self:
        if self.consented_at.tzinfo is None:
            raise ValueError("consent must carry a timezone-aware moment")
        return self


class ReferenceWord(_StrictModel):
    text: Token
    start_ms: Milliseconds
    end_ms: Milliseconds

    @model_validator(mode="after")
    def _span(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError("a word ends after it starts")
        return self


class Adjudication(_StrictModel):
    """A person listened to one word and decided what was said. Applied, never edited in."""

    word_index: Annotated[int, Field(strict=True, ge=0)]
    listened_by: Alias
    decided_at: datetime
    heard: Token
    reason: AdjudicationReason

    @model_validator(mode="after")
    def _aware(self) -> Self:
        if self.decided_at.tzinfo is None:
            raise ValueError("an adjudication carries a timezone-aware moment")
        return self


class GoldRecording(_StrictModel):
    recording_id: Alias
    condition: Condition
    private_path: str
    audio_sha256: Sha256
    audio_bytes: Annotated[int, Field(strict=True, gt=0)]
    duration_ms: Annotated[int, Field(strict=True, gt=0)]
    reference: tuple[ReferenceWord, ...]
    adjudications: tuple[Adjudication, ...] = ()

    @model_validator(mode="after")
    def _audio_stays_private(self) -> Self:
        path = PurePosixPath(self.private_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("private_path is relative to the repository root and never climbs")
        if not path.is_relative_to(PRIVATE_AUDIO_ROOT):
            raise ValueError(f"audio lives under {PRIVATE_AUDIO_ROOT}, nowhere else")
        if path.suffix.lower() not in AUDIO_SUFFIXES:
            raise ValueError("private_path must name an audio file")
        return self

    @model_validator(mode="after")
    def _reference_is_a_timeline(self) -> Self:
        if not self.reference:
            raise ValueError("a recording with no reference words cannot be scored")
        previous_end = 0
        for word in self.reference:
            if word.start_ms < previous_end:
                raise ValueError("reference words overlap or run backwards")
            previous_end = word.end_ms
        if previous_end > self.duration_ms:
            raise ValueError("a reference word ends after the recording does")
        return self

    @model_validator(mode="after")
    def _adjudications_point_at_words(self) -> Self:
        seen: set[tuple[int, str]] = set()
        for decision in self.adjudications:
            if decision.word_index >= len(self.reference):
                raise ValueError(
                    f"adjudication names word {decision.word_index}, which does not exist"
                )
            key = (decision.word_index, decision.listened_by)
            if key in seen:
                raise ValueError("one person adjudicates one word once")
            seen.add(key)
        return self


class GoldSetManifest(_StrictModel):
    version: Literal["voice-gold-set-v1"] = GOLD_SET_VERSION
    consent: Consent
    critical_terms: tuple[Term, ...]
    recordings: tuple[GoldRecording, ...]

    @model_validator(mode="after")
    def _recordings_are_distinct(self) -> Self:
        if not self.recordings:
            raise ValueError("an empty gold set selects nothing")
        ids = [r.recording_id for r in self.recordings]
        if len(ids) != len(set(ids)):
            raise ValueError("recording ids repeat")
        hashes = [r.audio_sha256 for r in self.recordings]
        if len(hashes) != len(set(hashes)):
            raise ValueError("two recordings claim the same audio")
        return self

    @model_validator(mode="after")
    def _consent_precedes_every_decision(self) -> Self:
        for recording in self.recordings:
            for decision in recording.adjudications:
                if decision.decided_at < self.consent.consented_at:
                    raise ValueError("an adjudication cannot predate the consent it depends on")
        return self

    @property
    def missing_conditions(self) -> tuple[Condition, ...]:
        present = {r.condition for r in self.recordings}
        return tuple(c for c in CONDITIONS if c not in present)


def adjudicated_reference(recording: GoldRecording) -> tuple[ReferenceWord, ...]:
    """The reference with every adjudication applied; the latest decision per word wins."""
    latest: dict[int, Adjudication] = {}
    for decision in recording.adjudications:
        current = latest.get(decision.word_index)
        if current is None or decision.decided_at > current.decided_at:
            latest[decision.word_index] = decision
    return tuple(
        ReferenceWord(text=latest[i].heard, start_ms=w.start_ms, end_ms=w.end_ms)
        if i in latest
        else w
        for i, w in enumerate(recording.reference)
    )


def reference_tokens(recording: GoldRecording) -> tuple[str, ...]:
    return tuple(w.text.casefold() for w in adjudicated_reference(recording))


def assert_no_raw_audio_committed(tracked_paths: Iterable[str], manifest: GoldSetManifest) -> None:
    """Refuse if a recording's audio, or any audio under the private root, is tracked."""
    tracked = {PurePosixPath(p) for p in tracked_paths}
    private = {PurePosixPath(r.private_path) for r in manifest.recordings}
    leaked = sorted(str(p) for p in tracked & private)
    if leaked:
        raise GoldSetError(f"raw audio is tracked: {leaked}")
    audio_under_root = sorted(
        str(p)
        for p in tracked
        if p.is_relative_to(PRIVATE_AUDIO_ROOT) and p.suffix.lower() in AUDIO_SUFFIXES
    )
    if audio_under_root:
        raise GoldSetError(f"audio under the private root is tracked: {audio_under_root}")


class GoldSetSummary(_StrictModel):
    """Everything a reviewer needs and nothing a listener would recognise."""

    version: Literal["voice-gold-set-v1"] = GOLD_SET_VERSION
    speaker_alias: Alias
    recordings: Annotated[int, Field(strict=True, ge=1)]
    total_duration_ms: Annotated[int, Field(strict=True, gt=0)]
    recordings_per_condition: dict[Condition, int]
    missing_conditions: tuple[Condition, ...]
    reference_words: Annotated[int, Field(strict=True, ge=1)]
    adjudicated_words: Annotated[int, Field(strict=True, ge=0)]
    adjudicators: Annotated[int, Field(strict=True, ge=0)]
    critical_terms: Annotated[int, Field(strict=True, ge=0)]
    audio_sha256: tuple[Sha256, ...]

    def render(self) -> str:
        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def summarize(manifest: GoldSetManifest) -> GoldSetSummary:
    per_condition: dict[Condition, int] = {c: 0 for c in CONDITIONS}
    adjudicated: set[tuple[str, int]] = set()
    adjudicators: set[str] = set()
    for recording in manifest.recordings:
        per_condition[recording.condition] += 1
        for decision in recording.adjudications:
            adjudicated.add((recording.recording_id, decision.word_index))
            adjudicators.add(decision.listened_by)
    return GoldSetSummary(
        speaker_alias=manifest.consent.speaker_alias,
        recordings=len(manifest.recordings),
        total_duration_ms=sum(r.duration_ms for r in manifest.recordings),
        recordings_per_condition=per_condition,
        missing_conditions=manifest.missing_conditions,
        reference_words=sum(len(r.reference) for r in manifest.recordings),
        adjudicated_words=len(adjudicated),
        adjudicators=len(adjudicators),
        critical_terms=len(manifest.critical_terms),
        audio_sha256=tuple(sorted(r.audio_sha256 for r in manifest.recordings)),
    )


def load_manifest(path: Path) -> GoldSetManifest:
    return GoldSetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    import argparse
    import subprocess

    parser = argparse.ArgumentParser(
        description="Validate a private gold-set manifest or summarize it."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--summary-out", type=Path, help="write the aggregate summary here")
    args = parser.parse_args(argv)
    manifest = load_manifest(args.manifest)
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=False
    ).stdout.splitlines()
    assert_no_raw_audio_committed(tracked, manifest)
    summary = summarize(manifest)
    if args.summary_out:
        args.summary_out.write_text(summary.render(), encoding="utf-8")
    missing = ", ".join(summary.missing_conditions) or "none"
    print(
        f"{summary.recordings} recordings, {summary.reference_words} reference words,"
        f" {summary.adjudicated_words} adjudicated, missing conditions: {missing}"
    )
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
