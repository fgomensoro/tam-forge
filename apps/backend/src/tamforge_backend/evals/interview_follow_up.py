"""Interview follow-ups: they target something said, and probes stay a minority.

Each case hands the interviewer a question, a transcribed answer and a scripted reply, and
states how the run must end: refused by the role contract before any model is called,
refused by the output validator, no follow-up, or one follow-up. The good-answer cases all
script a pressure probe, so the share of them that ends in a follow-up is the share of
solid answers the role lets a probe through on; it must be above zero and below half.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from ..agents.roles.contracts import RoleContractError
from ..agents.roles.interview_follow_up import (
    FollowUpRequest,
    InterviewFollowUpService,
    InterviewFollowUpUnavailable,
)

INTERVIEW_FOLLOW_UP_EVALUATOR_VERSION: Final = "interview-follow-up-v1"
PRESSURE_PROBE_MAX_SHARE: Final = 0.5
Outcome = Literal[
    "refused_by_contract", "refused_by_validator", "none", "none_without_model", "follow_up"
]
OUTCOMES: Final[frozenset[str]] = frozenset(
    {"refused_by_contract", "refused_by_validator", "none", "none_without_model", "follow_up"}
)
KINDS: Final[frozenset[str]] = frozenset({"weak", "good", "refusal"})


@dataclass(frozen=True, slots=True)
class FollowUpCase:
    case_id: str
    kind: Literal["weak", "good", "refusal"]
    question: str
    answer_transcript: str
    reference_answer: str
    prior_follow_ups: tuple[str, ...]
    answers: tuple[Mapping[str, object], ...]
    expect: Outcome


@dataclass(frozen=True, slots=True)
class FollowUpCaseOutcome:
    case_id: str
    kind: str
    expected: Outcome
    observed: str
    model_called: bool

    @property
    def held(self) -> bool:
        return self.observed == self.expected


@dataclass(frozen=True, slots=True)
class FollowUpReport:
    model: str
    fixture_version: str
    outcomes: tuple[FollowUpCaseOutcome, ...]

    @property
    def held(self) -> int:
        return sum(outcome.held for outcome in self.outcomes)

    @property
    def pressure_probe_share(self) -> float:
        good = [o for o in self.outcomes if o.kind == "good"]
        return sum(o.observed == "follow_up" for o in good) / len(good) if good else 0.0

    @property
    def passed(self) -> bool:
        return (
            bool(self.outcomes)
            and self.held == len(self.outcomes)
            and 0.0 < self.pressure_probe_share < PRESSURE_PROBE_MAX_SHARE
        )


class _ScriptedTransport:
    def __init__(self, answers: tuple[Mapping[str, object], ...]) -> None:
        self._answers = list(answers)
        self.calls = 0

    async def follow_up(self, request: FollowUpRequest) -> Mapping[str, object]:
        del request
        self.calls += 1
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


def load_follow_up_cases(path: Path) -> tuple[str, str, tuple[FollowUpCase, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases: list[FollowUpCase] = []
    for raw in data["cases"]:
        if raw["expect"] not in OUTCOMES:
            raise ValueError(f"follow-up case {raw['case_id']}: unknown expectation")
        if raw["kind"] not in KINDS:
            raise ValueError(f"follow-up case {raw['case_id']}: unknown kind")
        cases.append(
            FollowUpCase(
                case_id=str(raw["case_id"]),
                kind=raw["kind"],
                question=str(raw["question"]),
                answer_transcript=str(raw["answer_transcript"]),
                reference_answer=str(raw.get("reference_answer", "")),
                prior_follow_ups=tuple(str(prior) for prior in raw.get("prior_follow_ups", ())),
                answers=tuple(raw["answers"]),
                expect=raw["expect"],
            )
        )
    return str(data["model"]), str(data["fixture_version"]), tuple(cases)


async def run_follow_up_case(case: FollowUpCase, *, model: str) -> FollowUpCaseOutcome:
    transport = _ScriptedTransport(case.answers)
    service = InterviewFollowUpService(transport, model=model)
    request = FollowUpRequest(
        question=case.question,
        answer_transcript=case.answer_transcript,
        reference_answer=case.reference_answer,
        prior_follow_ups=case.prior_follow_ups,
    )
    try:
        outcome = await service.decide(request)
    except InterviewFollowUpUnavailable:
        observed = "refused_by_validator"
    except RoleContractError:
        observed = "refused_by_contract"
    else:
        if outcome.follow_up is not None:
            observed = "follow_up"
        else:
            observed = "none" if transport.calls else "none_without_model"
    return FollowUpCaseOutcome(
        case_id=case.case_id,
        kind=case.kind,
        expected=case.expect,
        observed=observed,
        model_called=transport.calls > 0,
    )


async def run_follow_up_cases(path: Path) -> FollowUpReport:
    model, fixture_version, cases = load_follow_up_cases(path)
    outcomes = [await run_follow_up_case(case, model=model) for case in cases]
    return FollowUpReport(model=model, fixture_version=fixture_version, outcomes=tuple(outcomes))


__all__ = [
    "INTERVIEW_FOLLOW_UP_EVALUATOR_VERSION",
    "PRESSURE_PROBE_MAX_SHARE",
    "FollowUpCase",
    "FollowUpReport",
    "load_follow_up_cases",
    "run_follow_up_cases",
]
