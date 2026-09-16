"""Weekly report refusals: every skill once, catalog-bound suggestions, no plan applied."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.weekly_report import (
    WeeklyReportRequest,
    WeeklyReportService,
    WeeklyReportUnavailable,
    WeeklySkillInput,
)

WEEKLY_REPORT_EVALUATOR_VERSION: Final = "weekly-report-refusals-v1"
Outcome = Literal["refused_by_contract", "refused_by_validator", "accepted"]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "accepted"}
)


@dataclass(frozen=True, slots=True)
class WeeklyReportCase:
    case_id: str
    week_start: date
    skills: tuple[WeeklySkillInput, ...]
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class WeeklyReportCaseOutcome:
    case_id: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class WeeklyReportReport:
    model: str
    fixture_version: str
    outcomes: tuple[WeeklyReportCaseOutcome, ...]

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

    async def weekly_report(self, request: WeeklyReportRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        if not self._answers:
            raise WeeklyReportUnavailable("the script ran out of answers")
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_weekly_report_cases(path: Path) -> tuple[str, str, tuple[WeeklyReportCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[WeeklyReportCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"report case {raw['case_id']}: unknown expectation {raw['expect']}")
        cases.append(
            WeeklyReportCase(
                case_id=str(raw["case_id"]),
                week_start=date.fromisoformat(str(raw["week_start"])),
                skills=tuple(
                    WeeklySkillInput(
                        slug=str(s["slug"]),
                        name=str(s["name"]),
                        level_at_start=str(s.get("level_at_start", "2")),
                        level_at_end=str(s.get("level_at_end", "2")),
                        events_this_week=int(s.get("events_this_week", 0)),
                    )
                    for s in raw["skills"]
                ),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_weekly_report_case(case: WeeklyReportCase, *, model: str) -> WeeklyReportCaseOutcome:
    from datetime import timedelta

    transport = _ScriptedTransport(case.answers)
    service = WeeklyReportService(transport, model=model)
    request = WeeklyReportRequest(
        week_start=case.week_start,
        week_end=case.week_start + timedelta(days=6),
        skills=case.skills,
        aggregates={"focused_minutes": 640, "planned_minutes": 900, "closed_days": 4},
    )
    try:
        await service.compose(request)
    except WeeklyReportUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        observed = "accepted"
    return WeeklyReportCaseOutcome(
        case_id=case.case_id,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_weekly_report_cases(path: Path) -> WeeklyReportReport:
    model, fixture_version, cases = load_weekly_report_cases(path)
    outcomes = [await run_weekly_report_case(case, model=model) for case in cases]
    return WeeklyReportReport(
        model=model, fixture_version=fixture_version, outcomes=tuple(outcomes)
    )


__all__ = [
    "WEEKLY_REPORT_EVALUATOR_VERSION",
    "WeeklyReportCase",
    "WeeklyReportReport",
    "load_weekly_report_cases",
    "run_weekly_report_cases",
]
