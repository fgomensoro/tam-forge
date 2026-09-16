"""The reviewer scores exactly the rubric, in half points, and never claims to act."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pytest
from tamforge_backend.agents.roles.contracts import RoleContractError
from tamforge_backend.agents.roles.reviewer import (
    ReviewBlock,
    ReviewDimension,
    ReviewerService,
    ReviewerUnavailable,
    ReviewRequest,
    render_review_prompt,
    validate_review,
)

DIMENSIONS = (
    ReviewDimension("correctness", "Correctness", Decimal(4)),
    ReviewDimension("structure", "Structure", Decimal(4)),
)
GOOD: dict[str, object] = {
    "verdict": "A correct answer with a weak close.",
    "dimensions": [
        {
            "slug": "correctness",
            "score": "3.5",
            "rationale": "Right idea.",
            "evidence": "200 means accepted",
        },
        {"slug": "structure", "score": "2", "rationale": "No close.", "evidence": "so yeah"},
    ],
    "strengths": [
        {"statement": "Names the durable acceptance rule."},
        {"statement": "Uses the right vocabulary."},
    ],
    "corrections": [
        {"statement": "Close with a decision.", "instruction": "End with the next action."},
        {"statement": "Name the retry policy.", "instruction": "State backoff and jitter."},
    ],
    "next_practice": "Answer the same prompt aloud in ninety seconds.",
}


class FakeTransport:
    def __init__(self, payloads: list[Mapping[str, object]]) -> None:
        self.payloads = list(payloads)
        self.requests: list[ReviewRequest] = []

    async def review(self, request: ReviewRequest) -> Mapping[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


def _request(**overrides: object) -> ReviewRequest:
    data: dict[str, object] = {
        "block": ReviewBlock("p1-w01-d01-roadmap", "Explain webhooks.", ("A note",), ("Accurate",)),
        "rubric_slug": "tam_block",
        "rubric_version": "seed-v1",
        "dimensions": DIMENSIONS,
        "committed_attempt": "Webhooks deliver events; 200 means accepted.",
        "self_review": "- Did well: named the rule",
    }
    data.update(overrides)
    return ReviewRequest(**data)  # type: ignore[arg-type]


def test_validation_accepts_the_rubric_and_refuses_everything_else() -> None:
    assert validate_review(GOOD, dimensions=DIMENSIONS) == ()
    only_one = {**GOOD, "dimensions": GOOD["dimensions"][:1]}  # type: ignore[index]
    assert "exactly the rubric" in validate_review(only_one, dimensions=DIMENSIONS)[0]
    too_high = {
        **GOOD,
        "dimensions": [{**GOOD["dimensions"][0], "score": "4.5"}, GOOD["dimensions"][1]],
    }  # type: ignore[index]
    assert "exceeds" in validate_review(too_high, dimensions=DIMENSIONS)[0]
    quarter = {
        **GOOD,
        "dimensions": [{**GOOD["dimensions"][0], "score": "3.25"}, GOOD["dimensions"][1]],
    }  # type: ignore[index]
    assert "half points" in validate_review(quarter, dimensions=DIMENSIONS)[0]
    claims = {**GOOD, "verdict": "Great, I marked this block as done."}
    assert "cannot claim" in validate_review(claims, dimensions=DIMENSIONS)[0]
    same = {**GOOD, "corrections": [GOOD["corrections"][0], GOOD["corrections"][0]]}  # type: ignore[index]
    assert "distinct" in validate_review(same, dimensions=DIMENSIONS)[0]
    assert validate_review({**GOOD, "done": True}, dimensions=DIMENSIONS)


@pytest.mark.anyio
async def test_a_review_returns_the_validated_outcome_and_the_prompt_carries_the_evidence() -> None:
    transport = FakeTransport([GOOD])
    service = ReviewerService(transport, model="claude-fable-5-1")

    outcome = await service.review(
        _request(
            transcript="0:00 other: tell me\n0:01 learner: hello",
            speech_metrics={"filler_count": 1},
        )
    )

    assert outcome.dimensions[0].score == Decimal("3.5")
    prompt = render_review_prompt(transport.requests[0])
    assert (
        "Rubric tam_block seed-v1" in prompt and "- correctness: Correctness (maximum 4)" in prompt
    )
    assert "Learner's self-review" in prompt and "0:01 learner: hello" in prompt
    assert "- filler_count: 1" in prompt and "never claim" in prompt


@pytest.mark.anyio
async def test_one_repair_then_refusal_and_contract_errors() -> None:
    bad = {**GOOD, "verdict": "I recorded the score."}
    with pytest.raises(ReviewerUnavailable):
        await ReviewerService(FakeTransport([bad, bad]), model="m").review(_request())
    with pytest.raises(ReviewerUnavailable):
        await ReviewerService(None, model="m").review(_request())
    with pytest.raises(RoleContractError, match="committed attempt"):
        await ReviewerService(FakeTransport([GOOD]), model="m").review(
            _request(committed_attempt=" ")
        )
    with pytest.raises(RoleContractError, match="rubric"):
        await ReviewerService(FakeTransport([GOOD]), model="m").review(_request(dimensions=()))
    transport = FakeTransport([bad, GOOD])
    repaired = await ReviewerService(transport, model="m").review(_request())
    assert repaired.verdict == GOOD["verdict"]
    assert transport.requests[1].repair_errors
