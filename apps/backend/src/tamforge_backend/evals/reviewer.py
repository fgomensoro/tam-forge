"""Reviewer refusals: scores stay inside the rubric, in half points, and never act.

Each case hands the reviewer a block, a rubric and a scripted answer, and states how the
turn must end: refused by the role contract before any model is called, refused by the
output validator after the model answered, or accepted. The scripted answers are the
model's worst behaviours written down (a score above the maximum, a dimension the rubric
does not have, a quarter-point score, a claim to have recorded the result), so the suite
proves the shape refuses them whatever the pinned model says.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.reviewer import (
    ReviewBlock,
    ReviewDimension,
    ReviewerService,
    ReviewerUnavailable,
    ReviewRequest,
)

REVIEWER_EVALUATOR_VERSION: Final = "reviewer-refusals-v1"
Outcome = Literal["refused_by_contract", "refused_by_validator", "accepted"]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "accepted"}
)


@dataclass(frozen=True, slots=True)
class ReviewerCase:
    case_id: str
    block: ReviewBlock
    dimensions: tuple[ReviewDimension, ...]
    committed_attempt: str
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class ReviewerCaseOutcome:
    case_id: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class ReviewerReport:
    model: str
    fixture_version: str
    outcomes: tuple[ReviewerCaseOutcome, ...]

    @property
    def held(self) -> int:
        return sum(outcome.held for outcome in self.outcomes)

    @property
    def passed(self) -> bool:
        return bool(self.outcomes) and self.held == len(self.outcomes)


class _ScriptedTransport:
    def __init__(self, answers: tuple[Mapping[str, object], ...]) -> None:
        self._answers = list(answers)
        self.calls = 0

    async def review(self, request: ReviewRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        if not self._answers:
            raise ReviewerUnavailable("the script ran out of answers")
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_reviewer_cases(path: Path) -> tuple[str, str, tuple[ReviewerCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[ReviewerCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"reviewer case {raw['case_id']}: unknown expectation {raw['expect']}")
        block = raw["block"]
        cases.append(
            ReviewerCase(
                case_id=str(raw["case_id"]),
                block=ReviewBlock(
                    stable_id=str(block["stable_id"]),
                    objective=str(block["objective"]),
                    required_output=tuple(block["required_output"]),
                    pass_criteria=tuple(block["pass_criteria"]),
                ),
                dimensions=tuple(
                    ReviewDimension(str(d["slug"]), str(d["name"]), Decimal(str(d["maximum"])))
                    for d in raw["dimensions"]
                ),
                committed_attempt=str(raw["committed_attempt"]),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_reviewer_case(case: ReviewerCase, *, model: str) -> ReviewerCaseOutcome:
    transport = _ScriptedTransport(case.answers)
    service = ReviewerService(transport, model=model)
    request = ReviewRequest(
        block=case.block,
        rubric_slug="tam_block",
        rubric_version="seed-v1",
        dimensions=case.dimensions,
        committed_attempt=case.committed_attempt,
    )
    try:
        await service.review(request)
    except ReviewerUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        observed = "accepted"
    return ReviewerCaseOutcome(
        case_id=case.case_id,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_reviewer_cases(path: Path) -> ReviewerReport:
    model, fixture_version, cases = load_reviewer_cases(path)
    outcomes = [await run_reviewer_case(case, model=model) for case in cases]
    return ReviewerReport(model=model, fixture_version=fixture_version, outcomes=tuple(outcomes))


__all__ = [
    "REVIEWER_EVALUATOR_VERSION",
    "ReviewerCase",
    "ReviewerReport",
    "load_reviewer_cases",
    "run_reviewer_cases",
]
