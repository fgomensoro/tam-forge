"""Where cards come from: approved study notes, accepted Coach proposals, and vault notes.

Every source produces `CardCommand`s; the service content-addresses them per owner, so
re-importing the same note or re-approving the same study note never duplicates a card.

A vault note opts in with `flashcard-source: true` in its front matter and lists its cards as
`Q:` / `A:` pairs. A question or answer may span several lines; a blank line or the next `Q:`
ends it. The optional `skill:` front-matter key names the skill the cards train.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..evidence.config_loader import load_config_payload
from ..evidence.models import ConfigSeedVersion
from .schemas import CardCommand

DEFAULT_SKILL_SLUG = "general"
SKILL_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
QUESTION_PREFIX = re.compile(r"^\s*\**\s*Q(?:uestion)?\s*\**\s*:\s*\**\s*(.*)$", re.IGNORECASE)
ANSWER_PREFIX = re.compile(r"^\s*\**\s*A(?:nswer)?\s*\**\s*:\s*\**\s*(.*)$", re.IGNORECASE)
MAX_PAIRS_PER_FILE = 200


@dataclass(frozen=True, slots=True)
class FlashcardNote:
    """A vault note that asked to be a card source, with the pairs it carries."""

    skill_slug: str
    pairs: tuple[tuple[str, str], ...]


def parse_front_matter(text: str) -> dict[str, str]:
    """The simple `key: value` front matter a vault note carries; nested values are ignored."""
    match = FRONT_MATTER.match(text)
    if match is None:
        return {}
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, _, value = line.partition(":")
        values[key.strip().lower()] = value.strip().strip("'\"")
    return values


def _flag(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"true", "yes", "1"}


def parse_flashcard_note(text: str) -> FlashcardNote | None:
    """The pairs in a vault note, or None when the note did not opt in as a card source."""
    front = parse_front_matter(text)
    if not _flag(front.get("flashcard-source")):
        return None
    skill = front.get("skill", "").strip()
    skill_slug = skill if SKILL_PATTERN.match(skill) else DEFAULT_SKILL_SLUG
    body = FRONT_MATTER.sub("", text, count=1)
    pairs: list[tuple[str, str]] = []
    question: list[str] | None = None
    answer: list[str] | None = None

    def close() -> None:
        nonlocal question, answer
        if question is not None and answer is not None:
            q, a = " ".join(question).strip(), " ".join(answer).strip()
            if q and a and len(pairs) < MAX_PAIRS_PER_FILE:
                pairs.append((q, a))
        question, answer = None, None

    for raw in body.splitlines():
        line = raw.rstrip()
        if (q_match := QUESTION_PREFIX.match(line)) is not None:
            close()
            question, answer = [q_match.group(1).strip()], None
        elif (a_match := ANSWER_PREFIX.match(line)) is not None and question is not None:
            answer = [a_match.group(1).strip()]
        elif not line.strip():
            close()
        elif answer is not None:
            answer.append(line.strip())
        elif question is not None:
            question.append(line.strip())
    close()
    return FlashcardNote(skill_slug=skill_slug, pairs=tuple(pairs))


def _bounded(question: str, answer: str) -> tuple[str, str]:
    return question[:2048], answer[:4096]


def package_card_commands(files: Mapping[str, bytes]) -> tuple[CardCommand, ...]:
    """Cards from every opted-in markdown note in an imported package, in path order."""
    commands: list[CardCommand] = []
    for path in sorted(files):
        if not path.lower().endswith(".md"):
            continue
        try:
            text = files[path].decode("utf-8")
        except UnicodeDecodeError:
            continue
        note = parse_flashcard_note(text)
        if note is None:
            continue
        for question, answer in note.pairs:
            question, answer = _bounded(question, answer)
            commands.append(
                CardCommand(
                    question=question,
                    answer=answer,
                    skill_slug=note.skill_slug,
                    source_kind="package",
                    source_ref=f"package:{path}"[:256],
                    assistance="independent",
                )
            )
    return tuple(commands)


def note_card_commands(
    *,
    note_id: int,
    flashcards: Iterable[tuple[str, str]],
    skill_slug: str,
    assistance: str,
) -> tuple[CardCommand, ...]:
    """Cards from an approved study note's flashcards; the note is their source."""
    coached: Literal["independent", "coached"] = (
        "coached" if assistance == "coached" else "independent"
    )
    commands: list[CardCommand] = []
    for question, answer in flashcards:
        question, answer = _bounded(question.strip(), answer.strip())
        if not question or not answer:
            continue
        commands.append(
            CardCommand(
                question=question,
                answer=answer,
                skill_slug=skill_slug,
                source_kind="study_note",
                source_ref=f"note:{note_id}",
                assistance=coached,
            )
        )
    return tuple(commands)


def coach_card_command(
    *, message_id: int, index: int, question: str, answer: str, skill_slug: str
) -> CardCommand:
    """A card the Coach proposed and the learner accepted, possibly edited first."""
    question, answer = _bounded(question.strip(), answer.strip())
    return CardCommand(
        question=question,
        answer=answer,
        skill_slug=skill_slug,
        source_kind="coach",
        source_ref=f"coach:{message_id}:{index}",
        assistance="coached",
    )


async def skill_slug_for(session: AsyncSession, *, owner_id: int, exercise_type: str | None) -> str:
    """The skill an activity's exercise trains most, from the seeded configuration."""
    if not exercise_type:
        return DEFAULT_SKILL_SLUG
    seeded = await session.scalar(
        select(ConfigSeedVersion)
        .where(ConfigSeedVersion.owner_id == owner_id)
        .order_by(ConfigSeedVersion.id.desc())
        .limit(1)
    )
    if seeded is None:
        return DEFAULT_SKILL_SLUG
    try:
        exercise = load_config_payload(seeded.canonical_payload).exercise(exercise_type)
    except (KeyError, ValueError):
        return DEFAULT_SKILL_SLUG
    always = [impact for impact in exercise.impacts if impact.condition == "always"]
    ranked = sorted(always or exercise.impacts, key=lambda impact: impact.weight, reverse=True)
    return ranked[0].skill_slug if ranked else DEFAULT_SKILL_SLUG


__all__ = [
    "DEFAULT_SKILL_SLUG",
    "FlashcardNote",
    "coach_card_command",
    "note_card_commands",
    "package_card_commands",
    "parse_flashcard_note",
    "parse_front_matter",
    "skill_slug_for",
]
