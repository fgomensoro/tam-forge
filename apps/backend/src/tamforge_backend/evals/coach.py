"""Coach refusals: no coaching where forbidden, no completion without evidence, no plan edits.

Each case hands the Coach a block, an attempt and a scripted answer, and states how the
turn must end: refused by the role contract before any model is called, refused by the
output validator after the model answered, or accepted. The scripted answers are the
model's worst behaviours written down (claiming a block is done, inventing a next step,
smuggling a score in as evidence), so the suite proves the shape refuses them whatever
the pinned model says. The report records the pinned model and the fixture hash; a
newer coach model is promoted when this part still passes on the same cases.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.coach import (
    CoachBlock,
    CoachRequest,
    CoachService,
    CoachUnavailable,
)
from ..agents.roles.contracts import RoleContractError

COACH_EVALUATOR_VERSION: Final = "coach-refusals-v1"
Outcome = Literal["refused_by_contract", "refused_by_validator", "accepted"]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "accepted"}
)


@dataclass(frozen=True, slots=True)
class CoachCase:
    case_id: str
    block: CoachBlock
    committed_attempt: str
    learner_message: str
    next_step: str
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class CoachCaseOutcome:
    case_id: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class CoachReport:
    model: str
    fixture_version: str
    outcomes: tuple[CoachCaseOutcome, ...]

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

    async def respond(self, request: CoachRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        if not self._answers:
            raise CoachUnavailable("the script ran out of answers")
        # The last scripted answer repeats, so a repair round sees the same misbehaviour.
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_coach_cases(path: Path) -> tuple[str, str, tuple[CoachCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[CoachCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"coach case {raw['case_id']}: unknown expectation {raw['expect']}")
        block = raw["block"]
        cases.append(
            CoachCase(
                case_id=str(raw["case_id"]),
                block=CoachBlock(
                    stable_id=str(block["stable_id"]),
                    objective=str(block["objective"]),
                    allowed_ai_role=str(block["allowed_ai_role"]),
                    required_output=tuple(block["required_output"]),
                    pass_criteria=tuple(block["pass_criteria"]),
                ),
                committed_attempt=str(raw["committed_attempt"]),
                learner_message=str(raw["learner_message"]),
                next_step=str(raw["next_step"]),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_coach_case(case: CoachCase, *, model: str) -> CoachCaseOutcome:
    transport = _ScriptedTransport(case.answers)
    service = CoachService(transport, model=model)
    request = CoachRequest(
        block=case.block,
        committed_attempt=case.committed_attempt,
        learner_message=case.learner_message,
        next_step=case.next_step,
    )
    try:
        await service.turn(request)
    except CoachUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        observed = "accepted"
    return CoachCaseOutcome(
        case_id=case.case_id,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_coach_cases(path: Path) -> CoachReport:
    model, fixture_version, cases = load_coach_cases(path)
    outcomes = [await run_coach_case(case, model=model) for case in cases]
    return CoachReport(model=model, fixture_version=fixture_version, outcomes=tuple(outcomes))
