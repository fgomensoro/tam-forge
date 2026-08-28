"""Fail-closed qualification rules for demonstrated evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
