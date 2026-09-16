"""Monthly report refusals: every skill once, the largest gaps as the ledger shows them."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.monthly_report import (
    MonthlyReportRequest,
    MonthlyReportService,
    MonthlyReportUnavailable,
    MonthlySkillInput,
)

MONTHLY_REPORT_EVALUATOR_VERSION: Final = "monthly-report-refusals-v1"
Outcome = Literal["refused_by_contract", "refused_by_validator", "accepted"]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "accepted"}
)


@dataclass(frozen=True, slots=True)
class MonthlyReportCase:
    case_id: str
    month_start: date
    skills: tuple[MonthlySkillInput, ...]
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class MonthlyReportCaseOutcome:
    case_id: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class MonthlyReportReport:
    model: str
    fixture_version: str
    outcomes: tuple[MonthlyReportCaseOutcome, ...]

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

    async def monthly_report(self, request: MonthlyReportRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        if not self._answers:
            raise MonthlyReportUnavailable("the script ran out of answers")
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_monthly_report_cases(path: Path) -> tuple[str, str, tuple[MonthlyReportCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[MonthlyReportCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"report case {raw['case_id']}: unknown expectation {raw['expect']}")
        cases.append(
            MonthlyReportCase(
                case_id=str(raw["case_id"]),
                month_start=date.fromisoformat(str(raw["month_start"])),
                skills=tuple(
                    MonthlySkillInput(
                        slug=str(s["slug"]),
                        name=str(s["name"]),
                        baseline=Decimal(str(s["baseline"])),
                        month_one_target=Decimal(str(s["month_one_target"])),
                        final_target=Decimal(str(s["final_target"])),
                        level_at_start=Decimal(str(s["level_at_start"])),
                        level_at_end=Decimal(str(s["level_at_end"])),
                        events_this_month=int(s.get("events_this_month", 0)),
                    )
                    for s in raw["skills"]
                ),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_monthly_report_case(
    case: MonthlyReportCase, *, model: str
) -> MonthlyReportCaseOutcome:
    from ..reports.monthly import month_end_of

    transport = _ScriptedTransport(case.answers)
    service = MonthlyReportService(transport, model=model)
    request = MonthlyReportRequest(
        month_start=case.month_start,
        month_end=month_end_of(case.month_start),
        skills=case.skills,
        aggregates={"focused_minutes": 2400, "closed_days": 18},
    )
    try:
        await service.compose(request)
    except MonthlyReportUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        observed = "accepted"
    return MonthlyReportCaseOutcome(
        case_id=case.case_id,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_monthly_report_cases(path: Path) -> MonthlyReportReport:
    model, fixture_version, cases = load_monthly_report_cases(path)
    outcomes = [await run_monthly_report_case(case, model=model) for case in cases]
    return MonthlyReportReport(
        model=model, fixture_version=fixture_version, outcomes=tuple(outcomes)
    )


__all__ = [
    "MONTHLY_REPORT_EVALUATOR_VERSION",
    "MonthlyReportCase",
    "MonthlyReportReport",
    "load_monthly_report_cases",
    "run_monthly_report_cases",
]
