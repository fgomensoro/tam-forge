"""The follow-up role: one short question about what was said, or nothing."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from tamforge_backend.agents.roles.contracts import RoleContractError
from tamforge_backend.agents.roles.interview_follow_up import (
    INTERVIEW_FOLLOW_UP_PROMPT_VERSION,
    INTERVIEW_FOLLOW_UP_SCHEMA_ID,
    NO_FOLLOW_UP,
    FollowUpRequest,
    InterviewFollowUpService,
    InterviewFollowUpUnavailable,
    follow_up_schema,
    pressure_probe_allowed,
    render_follow_up_prompt,
    validate_follow_up,
)

QUESTION = "Why are you leaving DataNest?"
ANSWER = (
    "I spent four years building DataNest from zero to twenty five customers and I loved "
    "the customer side. I hit the ceiling of what I can learn there, so I want to do it at scale."
)
# The probe gate is open for QUESTION/ANSWER and closed for this pair (see the gate test).
SOLID_QUESTION = "How do you prioritise competing requests?"
SOLID_ANSWER = (
    "I rank requests by revenue at risk and effort. Last quarter I had five open asks, I "
    "shipped the two that protected ninety thousand dollars in renewals and told the other "
    "three customers a date."
)
WEAK = {"follow_up": "What exactly was the ceiling you hit?", "reason": "weak_point"}


def test_a_short_question_about_what_was_said_or_nothing_passes() -> None:
    assert validate_follow_up(WEAK, answer_transcript=ANSWER) == ()
    assert validate_follow_up({"follow_up": None, "reason": None}, answer_transcript=ANSWER) == ()
    assert INTERVIEW_FOLLOW_UP_PROMPT_VERSION == "v1"
    assert INTERVIEW_FOLLOW_UP_SCHEMA_ID == "urn:tamforge:schema:interview-follow-up-v1"
    assert set(follow_up_schema()["required"]) == {"follow_up", "reason"}  # type: ignore[arg-type]


def test_invented_targets_double_questions_repeats_and_long_ones_are_refused() -> None:
    def issue(payload: Mapping[str, object], prior: tuple[str, ...] = ()) -> str:
        return validate_follow_up(payload, answer_transcript=ANSWER, prior_follow_ups=prior)[0]

    assert "both" in issue({"follow_up": None, "reason": "weak_point"})
    invented = {"follow_up": "How large was the Kubernetes migration budget?"}
    assert "actually said" in issue({**invented, "reason": "weak_point"})
    double = {"follow_up": "What was the ceiling? Who set it?", "reason": "weak_point"}
    assert "one spoken question" in issue(double)
    assert "already asked" in issue(WEAK, ("what exactly was the ceiling you hit",))
    wordy = {"follow_up": "What " + "so " * 31 + "was the ceiling?", "reason": "weak_point"}
    assert "at most 30 words" in issue(wordy)
    assert issue({"follow_up": "x" * 241 + "?", "reason": "weak_point"}).startswith("follow-up ")
    assert issue({**WEAK, "reason": "curiosity"}).startswith("follow-up reason")


def test_the_probe_gate_is_stable_and_the_prompt_says_which_case_it_is() -> None:
    assert pressure_probe_allowed(QUESTION, ANSWER) is True
    assert pressure_probe_allowed(SOLID_QUESTION, SOLID_ANSWER) is False
    request = FollowUpRequest(
        question=QUESTION,
        answer_transcript=ANSWER,
        reference_answer="Four anchors.",
        prior_follow_ups=("Why now?",),
        repair_errors=("one question only",),
    )
    prompt = render_follow_up_prompt(request)
    assert "Question asked: Why are you leaving DataNest?" in prompt and ANSWER in prompt
    assert "- Why now?" in prompt and "not something they said" in prompt
    assert "pressure probe" in prompt and "fix these:" in prompt
    closed = render_follow_up_prompt(
        FollowUpRequest(question=SOLID_QUESTION, answer_transcript=SOLID_ANSWER)
    )
    assert "ask nothing" in closed and "pressure probe" not in closed


class _Transport:
    def __init__(self, payloads: list[Mapping[str, object]]) -> None:
        self.payloads = payloads
        self.requests: list[FollowUpRequest] = []

    async def follow_up(self, request: FollowUpRequest) -> Mapping[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


def test_the_service_repairs_once_and_refuses_what_it_cannot_read() -> None:
    transport = _Transport([{"follow_up": "bad", "reason": "weak_point"}, dict(WEAK)])
    service = InterviewFollowUpService(transport, model="claude-fable-5-1")
    request = FollowUpRequest(question=QUESTION, answer_transcript=ANSWER)
    outcome = asyncio.run(service.decide(request))
    assert outcome.follow_up == WEAK["follow_up"] and outcome.reason == "weak_point"
    assert len(transport.requests) == 2 and transport.requests[1].repair_errors

    with pytest.raises(RoleContractError):
        asyncio.run(service.decide(FollowUpRequest(question=QUESTION, answer_transcript="Yes.")))
    with pytest.raises(RoleContractError):
        asyncio.run(service.decide(FollowUpRequest(question="  ", answer_transcript=ANSWER)))
    with pytest.raises(InterviewFollowUpUnavailable):
        asyncio.run(
            InterviewFollowUpService(None, model="m").decide(
                FollowUpRequest(question=QUESTION, answer_transcript=ANSWER)
            )
        )
    stubborn = _Transport([{"follow_up": "bad", "reason": "weak_point"}] * 2)
    with pytest.raises(InterviewFollowUpUnavailable):
        asyncio.run(
            InterviewFollowUpService(stubborn, model="m").decide(
                FollowUpRequest(question=QUESTION, answer_transcript=ANSWER)
            )
        )


def test_two_follow_ups_end_it_without_a_model_call_and_probes_obey_the_gate() -> None:
    idle = _Transport([])
    done = FollowUpRequest(
        question=QUESTION, answer_transcript=ANSWER, prior_follow_ups=("Why now?", "Why us?")
    )
    assert asyncio.run(InterviewFollowUpService(idle, model="m").decide(done)) == NO_FOLLOW_UP
    assert idle.requests == []

    probe = {"follow_up": "What would you do if the customers left?", "reason": "pressure_probe"}
    opened = InterviewFollowUpService(_Transport([dict(probe)]), model="m")
    kept = asyncio.run(opened.decide(FollowUpRequest(question=QUESTION, answer_transcript=ANSWER)))
    assert kept.reason == "pressure_probe"

    gated = {"follow_up": "How did you decide which renewals mattered?", "reason": "pressure_probe"}
    closed = InterviewFollowUpService(_Transport([gated]), model="m")
    dropped = asyncio.run(
        closed.decide(FollowUpRequest(question=SOLID_QUESTION, answer_transcript=SOLID_ANSWER))
    )
    assert dropped == NO_FOLLOW_UP
