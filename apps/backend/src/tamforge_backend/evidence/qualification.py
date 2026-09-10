"""Fail-closed qualification rules for demonstrated evidence.

A competency level moves only on evidence that qualifies, and it carries the events it
moved on. Both halves matter: a level that advances on unqualifying evidence is a claim
nobody can check, and a level that advances without keeping the link is a claim nobody
can audit later. `CompetencyAdvance` refuses to exist in either shape.

Readiness is derived from the levels rather than stored beside them, so there is no
second place it could advance from. The only way readiness moves is that a competency
did, and the only way a competency did is qualifying evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .config_models import FormulaConfig


class QualificationError(ValueError):
    """An evidence candidate is structurally invalid."""


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    event_id: int | str
    rubric_scored: bool
    practice_mode: str
    assistance: str
    evaluator: str
    attempt_kind: str
    exercise_type: str
    mapping_version: str
    scenario_key: str
    occurred_at: datetime
    ai_role: str
    required_precommit_field: str | None = None
    selected_competency: str | None = None
    allowed_selected_competencies: frozenset[str] = frozenset()
    selector_committed_before_attempt: bool = False

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise QualificationError("occurred_at must be timezone-aware")
        for name in ("exercise_type", "mapping_version", "scenario_key", "ai_role"):
            if not str(getattr(self, name)).strip():
                raise QualificationError(f"{name} must not be blank")


@dataclass(frozen=True, slots=True)
class QualificationResult:
    qualifying_for_level: bool
    reason: str


def qualify_evidence(
    candidate: EvidenceCandidate, *, formula: FormulaConfig
) -> QualificationResult:
    if formula.requires_rubric_score and not candidate.rubric_scored:
        return QualificationResult(False, "missing_rubric_score")
    if candidate.practice_mode not in formula.qualifying_modes:
        return QualificationResult(False, "nonqualifying_mode")
    if candidate.assistance not in formula.qualifying_assistance:
        return QualificationResult(False, "nonqualifying_assistance")
    if candidate.evaluator not in type(formula.evaluator_factors).model_fields:
        return QualificationResult(False, "unknown_evaluator")
    if not formula.attempt_b_qualifies and candidate.attempt_kind == "attempt_b":
        return QualificationResult(False, "attempt_b")
    if (
        formula.independent_practice_requires_attempt_a
        and candidate.practice_mode == "independent_practice"
        and candidate.attempt_kind != "attempt_a"
    ):
        return QualificationResult(False, "independent_requires_attempt_a")
    if candidate.required_precommit_field is not None:
        if candidate.selected_competency is None:
            return QualificationResult(False, "missing_precommit_selector")
        if (
            not candidate.selector_committed_before_attempt
            or candidate.selected_competency
            not in candidate.allowed_selected_competencies
        ):
            return QualificationResult(False, "invalid_precommit_selector")
    return QualificationResult(True, "qualifies")


def qualifies_as_transfer(
    *,
    prior: EvidenceCandidate,
    candidate: EvidenceCandidate,
    formula: FormulaConfig,
) -> bool:
    return (
        qualify_evidence(prior, formula=formula).qualifying_for_level
        and qualify_evidence(candidate, formula=formula).qualifying_for_level
        and candidate.attempt_kind == "attempt_a"
        and candidate.occurred_at > prior.occurred_at
        and candidate.scenario_key != prior.scenario_key
    )


CompetencyLevel = Literal["not_started", "practicing", "demonstrated"]
Readiness = Literal["not_ready", "partially_ready", "ready"]

# Three levels and no more: never shown it, working on it, shown it. Finer grades would
# be policy this rule does not have and cannot check.
COMPETENCY_LADDER: tuple[CompetencyLevel, ...] = ("not_started", "practicing", "demonstrated")


class CompetencyAdvanceError(ValueError):
    """A competency state that cannot be justified by the evidence it names."""


@dataclass(frozen=True, slots=True)
class CompetencyAdvance:
    """A level and every qualifying event that put it there."""

    level: CompetencyLevel
    qualifying_event_ids: tuple[int | str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.level not in COMPETENCY_LADDER:
            raise CompetencyAdvanceError("unknown competency level")
        if self.level != "not_started" and not self.qualifying_event_ids:
            raise CompetencyAdvanceError("a level above not_started must cite its evidence")
        if len(set(self.qualifying_event_ids)) != len(self.qualifying_event_ids):
            raise CompetencyAdvanceError("an event counts once")


def advance_competency(
    *,
    current: CompetencyLevel,
    candidate: EvidenceCandidate,
    formula: FormulaConfig,
    qualifying_event_ids: Sequence[int | str] = (),
) -> CompetencyAdvance:
    """Advance one step on qualifying evidence, or hold and say why it did not.

    Evidence that does not qualify changes nothing at all: not the level, and not the
    link. That is the whole rule. Evidence at the top of the ladder still joins the
    link, because more evidence for a demonstrated competency is still evidence.
    """
    if current not in COMPETENCY_LADDER:
        raise CompetencyAdvanceError("unknown competency level")
    kept = tuple(qualifying_event_ids)
    qualification = qualify_evidence(candidate, formula=formula)
    if not qualification.qualifying_for_level:
        return CompetencyAdvance(current, kept, qualification.reason)
    if candidate.event_id in kept:
        return CompetencyAdvance(current, kept, "already_counted")
    linked = (*kept, candidate.event_id)
    index = min(COMPETENCY_LADDER.index(current) + 1, len(COMPETENCY_LADDER) - 1)
    return CompetencyAdvance(COMPETENCY_LADDER[index], linked, "qualifies")


def readiness_from(levels: Mapping[str, CompetencyLevel]) -> Readiness:
    """Readiness is a reading of the levels, never a state of its own."""
    if not levels:
        return "not_ready"
    demonstrated = sum(1 for level in levels.values() if level == "demonstrated")
    if demonstrated == len(levels):
        return "ready"
    if demonstrated or any(level == "practicing" for level in levels.values()):
        return "partially_ready"
    return "not_ready"
