"""Practice review refusals: three dimensions, half points, verbatim quotes, no claims.

Each case hands the review a question, a transcribed answer, the learner's own reference
answer and a scripted reply, and states how the run must end: refused by the role contract
before any model is called, refused by the output validator after the model answered, or
accepted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.practice_review import (
    PracticeReviewRequest,
    PracticeReviewService,
    PracticeReviewUnavailable,
)

PRACTICE_REVIEW_EVALUATOR_VERSION: Final = "practice-review-refusals-v2"
Outcome = Literal["refused_by_contract", "refused_by_validator", "accepted"]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "accepted"}
)


@dataclass(frozen=True, slots=True)
class PracticeReviewCase:
    case_id: str
    question: str
    answer_transcript: str
    reference_answer: str
    follow_up_question: str
    parent_question: str
    parent_transcript: str
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class PracticeReviewCaseOutcome:
    case_id: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class PracticeReviewReport:
    model: str
    fixture_version: str
    outcomes: tuple[PracticeReviewCaseOutcome, ...]

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

    async def review_practice(self, request: PracticeReviewRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        if not self._answers:
            raise PracticeReviewUnavailable("the script ran out of answers")
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_practice_review_cases(path: Path) -> tuple[str, str, tuple[PracticeReviewCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[PracticeReviewCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"practice case {raw['case_id']}: unknown expectation {raw['expect']}")
        cases.append(
            PracticeReviewCase(
                case_id=str(raw["case_id"]),
                question=str(raw["question"]),
                answer_transcript=str(raw["answer_transcript"]),
                reference_answer=str(raw.get("reference_answer", "")),
                follow_up_question=str(raw.get("follow_up_question", "")),
                parent_question=str(raw.get("parent_question", "")),
                parent_transcript=str(raw.get("parent_transcript", "")),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_practice_review_case(
    case: PracticeReviewCase, *, model: str
) -> PracticeReviewCaseOutcome:
    transport = _ScriptedTransport(case.answers)
    service = PracticeReviewService(transport, model=model)
    request = PracticeReviewRequest(
        question=case.question,
        answer_transcript=case.answer_transcript,
        reference_answer=case.reference_answer,
        speech_metrics={"speech_rate_wpm": 126, "filler_count": 3},
        follow_up_question=case.follow_up_question,
        parent_question=case.parent_question,
        parent_transcript=case.parent_transcript,
    )
    try:
        await service.review(request)
    except PracticeReviewUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        observed = "accepted"
    return PracticeReviewCaseOutcome(
        case_id=case.case_id,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_practice_review_cases(path: Path) -> PracticeReviewReport:
    model, fixture_version, cases = load_practice_review_cases(path)
    outcomes = [await run_practice_review_case(case, model=model) for case in cases]
    return PracticeReviewReport(
        model=model, fixture_version=fixture_version, outcomes=tuple(outcomes)
    )


__all__ = [
    "PRACTICE_REVIEW_EVALUATOR_VERSION",
    "PracticeReviewCase",
    "PracticeReviewReport",
    "load_practice_review_cases",
    "run_practice_review_cases",
]
