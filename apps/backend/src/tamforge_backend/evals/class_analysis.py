"""Class analysis refusals: half points, verbatim examples, honest comparison, no claims.

Each case hands the analysis a class record, speech and vocabulary measures, the previous
classes and a scripted answer, and states how the run must end: refused by the role
contract before any model is called, refused by the output validator after the model
answered, or accepted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.class_analysis import (
    ClassAnalysisRequest,
    ClassAnalysisService,
    ClassAnalysisUnavailable,
    ClassRecord,
    PreviousClass,
)
from ..agents.roles.contracts import RoleContractError

CLASS_ANALYSIS_EVALUATOR_VERSION: Final = "class-analysis-refusals-v1"
Outcome = Literal["refused_by_contract", "refused_by_validator", "accepted"]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "accepted"}
)


@dataclass(frozen=True, slots=True)
class ClassAnalysisCase:
    case_id: str
    record: ClassRecord
    transcript: str
    previous: tuple[PreviousClass, ...]
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class ClassAnalysisCaseOutcome:
    case_id: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class ClassAnalysisReport:
    model: str
    fixture_version: str
    outcomes: tuple[ClassAnalysisCaseOutcome, ...]

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

    async def analyse_class(self, request: ClassAnalysisRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        if not self._answers:
            raise ClassAnalysisUnavailable("the script ran out of answers")
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_class_analysis_cases(path: Path) -> tuple[str, str, tuple[ClassAnalysisCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[ClassAnalysisCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"class case {raw['case_id']}: unknown expectation {raw['expect']}")
        record = raw["record"]
        cases.append(
            ClassAnalysisCase(
                case_id=str(raw["case_id"]),
                record=ClassRecord(
                    teacher=str(record["teacher"]),
                    starts_at=datetime.fromisoformat(str(record["starts_at"])).astimezone(UTC),
                    expected_duration_minutes=int(record["expected_duration_minutes"]),
                    notes=str(record.get("notes", "")),
                ),
                transcript=str(raw["transcript"]),
                previous=tuple(
                    PreviousClass(
                        starts_at=datetime.fromisoformat(str(p["starts_at"])).astimezone(UTC),
                        fluency_score=Decimal(str(p["fluency_score"])),
                        vocabulary_score=Decimal(str(p["vocabulary_score"])),
                        recurring_errors=tuple(str(e) for e in p.get("recurring_errors", [])),
                    )
                    for p in raw.get("previous", [])
                ),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_class_analysis_case(
    case: ClassAnalysisCase, *, model: str
) -> ClassAnalysisCaseOutcome:
    transport = _ScriptedTransport(case.answers)
    service = ClassAnalysisService(transport, model=model)
    request = ClassAnalysisRequest(
        record=case.record,
        transcript=case.transcript,
        speech_metrics={"speech_rate_wpm": 118, "filler_count": 4},
        vocabulary_metrics={"unique_words": 40, "type_token_ratio": 0.6},
        previous=case.previous,
    )
    try:
        await service.analyse(request)
    except ClassAnalysisUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        observed = "accepted"
    return ClassAnalysisCaseOutcome(
        case_id=case.case_id,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_class_analysis_cases(path: Path) -> ClassAnalysisReport:
    model, fixture_version, cases = load_class_analysis_cases(path)
    outcomes = [await run_class_analysis_case(case, model=model) for case in cases]
    return ClassAnalysisReport(
        model=model, fixture_version=fixture_version, outcomes=tuple(outcomes)
    )


__all__ = [
    "CLASS_ANALYSIS_EVALUATOR_VERSION",
    "ClassAnalysisCase",
    "ClassAnalysisReport",
    "load_class_analysis_cases",
    "run_class_analysis_cases",
]
