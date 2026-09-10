"""Workspace session rules: phase timing, source visibility, AI locks, and commitments.

Two specialized workspaces live here. The SQL workspace exists to make a learner's own
reasoning visible before any assistance touches it, so three rules are structural
rather than advisory. Assistance is locked
until the learner commits an attempt or the primary-work clock runs out. Hints are
revealed one rung at a time in a fixed order, and the last rung, the full solution, is
unreachable until an attempt has been saved. The committed record then carries both
the rung the learner reached and the canonical category of the mistake, so later
scoring can tell unassisted work from assisted work instead of guessing.

The technical-reading workspace answers a different question. Its five timeboxes exist
so that recall is recall: the source is visible while previewing and reading and gone
from the moment recall starts, and no clock lets the tutor in early. The note the
learner writes from memory carries four fields, and all four are required, because a
note missing its boundary case or its customer example is the note someone writes when
they did not understand the reading.

The assistance vocabulary here is the same closed set the evidence tables accept, and
`apps/backend/tests/unit/workspaces/test_sql.py` asserts the two agree, as
`test_reading.py` does for the recall-note fields. A value that drifts apart would
produce a commitment the database rejects at write time.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SqlPhase = Literal["retrieval", "primary_work", "validation", "self_review"]

PHASE_ORDER: tuple[SqlPhase, ...] = ("retrieval", "primary_work", "validation", "self_review")
PHASE_SECONDS: Mapping[SqlPhase, int] = MappingProxyType(
    {"retrieval": 300, "primary_work": 1_800, "validation": 300, "self_review": 300}
)
SESSION_SECONDS = sum(PHASE_SECONDS.values())
# Assistance opens here whether or not the learner committed: an expired clock is the
# other way out of the lock, and leaving someone stuck with no help is not the point.
PRIMARY_WORK_DEADLINE_SECONDS = PHASE_SECONDS["retrieval"] + PHASE_SECONDS["primary_work"]

# Ordered from the smallest nudge to the answer itself. The index is the rung: rung 1
# is HINT_LADDER[0], and rung 0 means no hint has been taken.
HINT_LADDER: tuple[str, ...] = (
    "restate_goal",
    "locate_tables",
    "name_the_operation",
    "query_skeleton",
    "full_solution",
)
NO_HINT_LEVEL = 0
SOLUTION_HINT_LEVEL = len(HINT_LADDER)

AiLockReason = Literal["unlocked", "awaiting_commitment"]

# Closed taxonomy. "none" belongs to a matched result only; a wrong answer with no
# named mistake is an unrecorded one, which is what this taxonomy exists to prevent.
MistakeCategory = Literal[
    "none",
    "misread_question",
    "wrong_grain",
    "missing_filter",
    "wrong_join_type",
    "null_handling",
    "ungrouped_aggregate",
    "ordering_or_limit",
    "type_or_cast",
    "syntax_error",
]

AssistanceCode = Literal[
    "no_ai",
    "ai_after_committed_attempt",
    "ai_hints_during_attempt",
    "ai_co_created",
    "ai_generated",
]
QUALIFYING_ASSISTANCE: frozenset[str] = frozenset({"no_ai", "ai_after_committed_attempt"})

LearnerText = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=8_192, pattern=r"\S")
]


ReadingPhase = Literal["preview", "reading", "recall", "application", "teach_back"]

READING_PHASE_ORDER: tuple[ReadingPhase, ...] = (
    "preview",
    "reading",
    "recall",
    "application",
    "teach_back",
)
READING_PHASE_SECONDS: Mapping[ReadingPhase, int] = MappingProxyType(
    {"preview": 120, "reading": 1_200, "recall": 480, "application": 600, "teach_back": 300}
)
READING_SESSION_SECONDS = sum(READING_PHASE_SECONDS.values())

# The source is available while previewing and reading, and gone from the moment recall
# starts. Recall that can consult the source is not recall.
SOURCE_VISIBLE_PHASES: frozenset[str] = frozenset({"preview", "reading"})

# The four fields of the recall note. This set is the same one `LEARNER_FIELDS["reading"]`
# declares in the backend's redaction layer; a backend test compares them.
READING_NOTE_FIELDS: frozenset[str] = frozenset(
    {"key_ideas", "boundary_or_failure", "tam_customer_example", "unresolved_question"}
)
REQUIRED_KEY_IDEAS = 3


class WorkspaceRuleError(ValueError):
    """A session rule refused the request. The message names the rule, never learner text."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def phase_at(elapsed_seconds: int) -> SqlPhase | None:
    """Return the phase the session is in, or None once it has ended."""
    if elapsed_seconds < 0:
        raise WorkspaceRuleError("elapsed time cannot be negative")
    boundary = 0
    for phase in PHASE_ORDER:
        boundary += PHASE_SECONDS[phase]
        if elapsed_seconds < boundary:
            return phase
    return None


def ai_lock_reason(*, committed: bool, elapsed_seconds: int) -> AiLockReason:
    """Assistance opens on the learner's commitment, or when the work clock expires."""
    if elapsed_seconds < 0:
        raise WorkspaceRuleError("elapsed time cannot be negative")
    if committed or elapsed_seconds >= PRIMARY_WORK_DEADLINE_SECONDS:
        return "unlocked"
    return "awaiting_commitment"


def reveal_hint(
    *,
    reached_level: int,
    requested_level: int,
    committed: bool,
    elapsed_seconds: int,
    saved_attempt: bool = False,
) -> int:
    """Return the rung reached after this request, or refuse the request outright."""
    if ai_lock_reason(committed=committed, elapsed_seconds=elapsed_seconds) != "unlocked":
        raise WorkspaceRuleError(
            "assistance is locked until the attempt is committed or the clock expires"
        )
    if not NO_HINT_LEVEL < requested_level <= SOLUTION_HINT_LEVEL:
        raise WorkspaceRuleError("requested hint is not a rung on the ladder")
    if requested_level <= reached_level:
        # Re-reading a rung already taken costs nothing and reveals nothing new.
        return reached_level
    if requested_level > reached_level + 1:
        raise WorkspaceRuleError("hints are revealed in order, one rung at a time")
    if requested_level == SOLUTION_HINT_LEVEL and not saved_attempt:
        raise WorkspaceRuleError("the solution is revealed only after a saved attempt")
    return requested_level


def assistance_code(*, reached_level: int, hints_taken_before_commitment: bool) -> AssistanceCode:
    """Map the rung the learner reached onto the evidence layer's assistance vocabulary."""
    if reached_level <= NO_HINT_LEVEL:
        return "no_ai"
    if reached_level >= SOLUTION_HINT_LEVEL:
        return "ai_generated"
    if hints_taken_before_commitment:
        return "ai_hints_during_attempt"
    return "ai_after_committed_attempt"


def qualifies_as_evidence(assistance: str) -> bool:
    return assistance in QUALIFYING_ASSISTANCE


class SqlAttemptCommitment(_StrictModel):
    """The immutable record a saved SQL attempt leaves behind."""

    exercise_key: Annotated[
        str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    ]
    exercise_version: Annotated[int, Field(strict=True, gt=0)]
    query: LearnerText
    result_validation: Literal["matched", "mismatch", "wrong_grain"]
    explanation: LearnerText
    business_meaning: LearnerText
    self_review: LearnerText
    reached_hint_level: Annotated[int, Field(strict=True, ge=NO_HINT_LEVEL, le=SOLUTION_HINT_LEVEL)]
    mistake_category: MistakeCategory
    assistance: AssistanceCode
    elapsed_seconds: Annotated[int, Field(strict=True, ge=0, le=SESSION_SECONDS)]

    @property
    def qualifies_as_evidence(self) -> bool:
        return self.assistance in QUALIFYING_ASSISTANCE

    @model_validator(mode="after")
    def assistance_matches_the_rung(self) -> Self:
        if self.reached_hint_level == NO_HINT_LEVEL and self.assistance != "no_ai":
            raise ValueError("an unassisted attempt cannot claim assistance")
        if self.reached_hint_level > NO_HINT_LEVEL and self.assistance == "no_ai":
            raise ValueError("an attempt that took a hint is not unassisted")
        if (self.reached_hint_level == SOLUTION_HINT_LEVEL) != (self.assistance == "ai_generated"):
            raise ValueError("a revealed solution is recorded as ai_generated and nothing else")
        return self

    @model_validator(mode="after")
    def a_failed_result_names_its_mistake(self) -> Self:
        if self.result_validation != "matched" and self.mistake_category == "none":
            raise ValueError("a result that did not match must name its mistake category")
        return self


def reading_phase_at(elapsed_seconds: int) -> ReadingPhase | None:
    """Return the reading phase the session is in, or None once it has ended."""
    if elapsed_seconds < 0:
        raise WorkspaceRuleError("elapsed time cannot be negative")
    boundary = 0
    for phase in READING_PHASE_ORDER:
        boundary += READING_PHASE_SECONDS[phase]
        if elapsed_seconds < boundary:
            return phase
    return None


def source_visible(phase: ReadingPhase | None) -> bool:
    """A finished session shows no source either, so None is not visible."""
    return phase in SOURCE_VISIBLE_PHASES


def reading_ai_lock_reason(*, note_committed: bool) -> AiLockReason:
    """The tutor opens on the committed note and on nothing else.

    Unlike the SQL workspace, no expiring clock lets assistance in. A recall note the
    learner never wrote is not a recall note, and a tutor that fills it in has replaced
    the exercise rather than evaluated it.
    """
    return "unlocked" if note_committed else "awaiting_commitment"


class ReadingRecallNote(_StrictModel):
    """What the learner writes from memory, with the source already hidden."""

    key_ideas: Annotated[
        tuple[LearnerText, ...],
        Field(min_length=REQUIRED_KEY_IDEAS, max_length=REQUIRED_KEY_IDEAS),
    ]
    boundary_or_failure: LearnerText
    tam_customer_example: LearnerText
    unresolved_question: LearnerText

    @model_validator(mode="after")
    def distinct_key_ideas(self) -> Self:
        # Three copies of one idea is one idea, and passing the count that way turns the
        # requirement into a typing exercise.
        if len({idea.strip().casefold() for idea in self.key_ideas}) != REQUIRED_KEY_IDEAS:
            raise ValueError("the key ideas must be distinct")
        return self


__all__ = [
    "HINT_LADDER",
    "NO_HINT_LEVEL",
    "PHASE_ORDER",
    "PHASE_SECONDS",
    "PRIMARY_WORK_DEADLINE_SECONDS",
    "QUALIFYING_ASSISTANCE",
    "READING_NOTE_FIELDS",
    "READING_PHASE_ORDER",
    "READING_PHASE_SECONDS",
    "READING_SESSION_SECONDS",
    "REQUIRED_KEY_IDEAS",
    "SESSION_SECONDS",
    "SOLUTION_HINT_LEVEL",
    "AiLockReason",
    "AssistanceCode",
    "MistakeCategory",
    "ReadingPhase",
    "ReadingRecallNote",
    "SOURCE_VISIBLE_PHASES",
    "SqlAttemptCommitment",
    "SqlPhase",
    "WorkspaceRuleError",
    "ai_lock_reason",
    "assistance_code",
    "phase_at",
    "qualifies_as_evidence",
    "reading_ai_lock_reason",
    "reading_phase_at",
    "reveal_hint",
    "source_visible",
]
