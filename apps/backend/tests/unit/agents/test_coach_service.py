from __future__ import annotations

from collections.abc import Mapping

import pytest
from tamforge_backend.agents.roles.coach import (
    CoachBlock,
    CoachRequest,
    CoachService,
    CoachUnavailable,
    coaching_allowed,
    render_coach_prompt,
    validate_coach_turn,
)
from tamforge_backend.agents.roles.contracts import RoleContractError

BLOCK = CoachBlock(
    stable_id="p1-w01-d01-roadmap",
    objective="Explain webhook delivery and retries.",
    allowed_ai_role="coach",
    required_output=("A committed closed-source recall note.",),
    pass_criteria=("Explain the concept accurately.",),
)
NEXT = "Commit the recall note, then start the pipeline block."
GOOD = {
    "message": "Your note covers delivery but not retries. Add the backoff rule.",
    "next_step": NEXT,
    "proposed_evidence": [{"kind": "note", "text": "Retries use exponential backoff with jitter."}],
}


class FakeTransport:
    def __init__(self, payloads: list[Mapping[str, object]]) -> None:
        self.payloads = list(payloads)
        self.requests: list[CoachRequest] = []

    async def respond(self, request: CoachRequest) -> Mapping[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


def _request(**overrides: object) -> CoachRequest:
    data: dict[str, object] = {
        "block": BLOCK,
        "committed_attempt": "Webhooks deliver events over HTTP; 200 means accepted.",
        "learner_message": "ya lo hice",
        "next_step": NEXT,
    }
    data.update(overrides)
    return CoachRequest(**data)  # type: ignore[arg-type]


def test_coaching_is_allowed_only_where_the_block_says_so() -> None:
    assert coaching_allowed(BLOCK)
    assert coaching_allowed(CoachBlock("x", "o", "tutor", (), ()))
    assert not coaching_allowed(CoachBlock("x", "o", "none", (), ()))
    assert not coaching_allowed(CoachBlock("x", "o", "interviewer", (), ()))


def test_turn_validation_refuses_completion_claims_and_invented_next_steps() -> None:
    assert validate_coach_turn(GOOD, next_step=NEXT) == ()
    assert validate_coach_turn({**GOOD, "next_step": "Skip to Saturday."}, next_step=NEXT)
    assert validate_coach_turn({**GOOD, "done": True}, next_step=NEXT)
    assert validate_coach_turn(
        {**GOOD, "message": "Great, I marked this block as done."}, next_step=NEXT
    )
    assert validate_coach_turn({**GOOD, "message": "x" * 2001}, next_step=NEXT)
    assert validate_coach_turn(
        {**GOOD, "proposed_evidence": [{"kind": "score", "text": "4/5"}]}, next_step=NEXT
    )


@pytest.mark.anyio
async def test_a_turn_returns_the_validated_message_and_evidence() -> None:
    transport = FakeTransport([GOOD])
    service = CoachService(transport, model="claude-opus-5")

    turn = await service.turn(_request())

    assert turn.next_step == NEXT
    assert turn.proposed_evidence[0].kind == "note"
    assert transport.requests[0].learner_message == "ya lo hice"


@pytest.mark.anyio
async def test_one_repair_then_refusal_and_runtime_failures_are_unavailable() -> None:
    bad = {**GOOD, "next_step": "Something else"}
    service = CoachService(FakeTransport([bad, bad]), model="m")
    with pytest.raises(CoachUnavailable):
        await service.turn(_request())

    disabled = CoachService(None, model="m")
    with pytest.raises(CoachUnavailable):
        await disabled.turn(_request())


@pytest.mark.anyio
async def test_the_coach_refuses_forbidden_blocks_and_uncommitted_attempts() -> None:
    service = CoachService(FakeTransport([GOOD]), model="m")
    with pytest.raises(RoleContractError, match="does not allow coaching"):
        await service.turn(_request(block=CoachBlock("s", "o", "none", (), ())))
    with pytest.raises(RoleContractError, match="only after the learner commits"):
        await service.turn(_request(committed_attempt="   "))


def test_the_prompt_carries_the_brief_the_attempt_and_repair_errors() -> None:
    prompt = render_coach_prompt(
        _request(
            self_review="I rushed the retries part.",
            prior_messages=(("learner", "first"), ("coach", "reply")),
            repair_errors=("the next step must be the plan's, not the coach's",),
        )
    )
    assert "Objective: Explain webhook delivery" in prompt
    assert f"next_step): {NEXT}" in prompt
    assert "Self-review:" in prompt and "coach: reply" in prompt
    assert "fix these" in prompt
