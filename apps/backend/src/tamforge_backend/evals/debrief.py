"""Debrief refusals: quotes come from the transcript, skills from the catalog, no plan edits.

Each case hands the debrief an interview record, a skill catalog and a scripted answer, and
states how the run must end: refused by the role contract before any model is called,
refused by the output validator after the model answered, or accepted. The scripted
answers are the model's worst behaviours written down (an invented quote, a skill outside
the catalog, a claim to have rescheduled the plan), so the suite proves the shape refuses
them whatever the pinned model says.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.debrief import (
    DebriefInterview,
    DebriefRequest,
    DebriefService,
    DebriefSkill,
    DebriefUnavailable,
)

DEBRIEF_EVALUATOR_VERSION: Final = "debrief-refusals-v1"
Outcome = Literal["refused_by_contract", "refused_by_validator", "accepted"]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "accepted"}
)


@dataclass(frozen=True, slots=True)
class DebriefCase:
    case_id: str
    interview: DebriefInterview
    skills: tuple[DebriefSkill, ...]
    transcript: str
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class DebriefCaseOutcome:
    case_id: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class DebriefReport:
    model: str
    fixture_version: str
    outcomes: tuple[DebriefCaseOutcome, ...]

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

    async def debrief(self, request: DebriefRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        if not self._answers:
            raise DebriefUnavailable("the script ran out of answers")
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_debrief_cases(path: Path) -> tuple[str, str, tuple[DebriefCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[DebriefCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"debrief case {raw['case_id']}: unknown expectation {raw['expect']}")
        interview = raw["interview"]
        cases.append(
            DebriefCase(
                case_id=str(raw["case_id"]),
                interview=DebriefInterview(
                    company=str(interview["company"]),
                    role=str(interview["role"]),
                    stage=str(interview["stage"]),
                    starts_at=datetime.fromisoformat(str(interview["starts_at"])).astimezone(UTC),
                    status=str(interview["status"]),
                ),
                skills=tuple(DebriefSkill(str(s["slug"]), str(s["name"])) for s in raw["skills"]),
                transcript=str(raw["transcript"]),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_debrief_case(case: DebriefCase, *, model: str) -> DebriefCaseOutcome:
    transport = _ScriptedTransport(case.answers)
    service = DebriefService(transport, model=model)
    request = DebriefRequest(
        interview=case.interview, transcript=case.transcript, skills=case.skills
    )
    try:
        await service.debrief(request)
    except DebriefUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        observed = "accepted"
    return DebriefCaseOutcome(
        case_id=case.case_id,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_debrief_cases(path: Path) -> DebriefReport:
    model, fixture_version, cases = load_debrief_cases(path)
    outcomes = [await run_debrief_case(case, model=model) for case in cases]
    return DebriefReport(model=model, fixture_version=fixture_version, outcomes=tuple(outcomes))


__all__ = [
    "DEBRIEF_EVALUATOR_VERSION",
    "DebriefCase",
    "DebriefReport",
    "load_debrief_cases",
    "run_debrief_cases",
]
