"""The practice review role: three dimensions, half points, verbatim quotes, no claims."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest
from tamforge_backend.agents.roles.contracts import RoleContractError
from tamforge_backend.agents.roles.practice_review import (
    PRACTICE_DIMENSIONS,
    PracticeReviewRequest,
    PracticeReviewService,
    PracticeReviewUnavailable,
    render_practice_review_prompt,
    validate_practice_review,
)

QUESTION = "Why are you leaving DataNest?"
ANSWER = (
    "I spent four years building DataNest from zero to twenty five customers and I loved "
    "the customer side. I hit the ceiling of what I can learn there, so I want to do it at scale."
)
REFERENCE = "Four anchors: four years, alone, ceiling, scale."


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "dimensions": [
            {
                "slug": "answer_clarity",
                "score": "3.0",
                "evidence": "I hit the ceiling of what I can learn there",
                "note": "Four clear sentences.",
            },
            {
                "slug": "technical_examples",
                "score": "2.0",
                "evidence": "from zero to twenty five customers",
                "note": "One number, no example of a process built.",
            },
            {
                "slug": "english_accuracy",
                "score": "3.5",
                "evidence": "I loved the customer side",
                "note": "Accurate simple past.",
            },
        ],
        "strengths": ["Opens with the four years and the number."],
        "fixes": [
            {
                "heard": "I want to do it at scale",
                "say_instead": "I want to do it at real scale, with a team I can learn from",
                "why": "The reference answer ends on the team.",
            }
        ],
        "reference_coverage": "The 'alone' anchor is missing.",
        "readiness": "drilling",
    }
    base.update(overrides)
    return base


def _request(**overrides: object) -> PracticeReviewRequest:
    values: dict[str, object] = {
        "question": QUESTION,
        "answer_transcript": ANSWER,
        "reference_answer": REFERENCE,
        "speech_metrics": {"speech_rate_wpm": 131},
    }
    values.update(overrides)
    return PracticeReviewRequest(**values)  # type: ignore[arg-type]


def test_a_quoted_half_point_review_of_the_three_dimensions_passes() -> None:
    assert [slug for slug, _ in PRACTICE_DIMENSIONS] == [
        "answer_clarity",
        "technical_examples",
        "english_accuracy",
    ]
    assert validate_practice_review(_payload(), answer_transcript=ANSWER) == ()


def test_missing_dimensions_quarter_points_invented_quotes_and_claims_are_refused() -> None:
    two = _payload(dimensions=_payload()["dimensions"][:2])  # type: ignore[index]
    assert "exactly" in validate_practice_review(two, answer_transcript=ANSWER)[0]
    dims = [dict(d) for d in _payload()["dimensions"]]  # type: ignore[union-attr]
    dims[0]["score"] = "2.75"
    assert (
        "half points"
        in validate_practice_review(_payload(dimensions=dims), answer_transcript=ANSWER)[0]
    )
    dims = [dict(d) for d in _payload()["dimensions"]]  # type: ignore[union-attr]
    dims[1]["evidence"] = "we saved forty thousand dollars"
    assert (
        "verbatim"
        in validate_practice_review(_payload(dimensions=dims), answer_transcript=ANSWER)[0]
    )
    invented_fix = _payload(
        fixes=[{"heard": "I was fired", "say_instead": "I resigned", "why": "accuracy"}]
    )
    assert "heard" in validate_practice_review(invented_fix, answer_transcript=ANSWER)[0]
    claimed = _payload(reference_coverage="I recorded this as READY in your answer bank.")
    assert "cannot claim" in validate_practice_review(claimed, answer_transcript=ANSWER)[0]
    assert validate_practice_review(_payload(readiness="perfect"), answer_transcript=ANSWER)[
        0
    ].startswith("review ")


def test_the_prompt_carries_the_question_the_answer_and_the_unverified_reference() -> None:
    prompt = render_practice_review_prompt(_request(repair_errors=("score in half points",)))
    assert "Question asked: Why are you leaving DataNest?" in prompt
    assert ANSWER in prompt
    assert "The learner's own reference answer (what they intended to say, not evidence" in prompt
    assert "- speech_rate_wpm: 131" in prompt
    assert "fix these:" in prompt
    without = render_practice_review_prompt(_request(reference_answer=""))
    assert "what they intended to say" not in without


class _Transport:
    def __init__(self, payloads: list[Mapping[str, object]]) -> None:
        self.payloads = payloads
        self.requests: list[PracticeReviewRequest] = []

    async def review_practice(self, request: PracticeReviewRequest) -> Mapping[str, object]:
        self.requests.append(request)
        return self.payloads.pop(0)


def test_the_service_repairs_once_refuses_short_answers_and_needs_claude() -> None:
    bad = _payload(readiness="perfect")
    transport = _Transport([bad, _payload()])
    service = PracticeReviewService(transport, model="claude-fable-5-1")
    outcome = asyncio.run(service.review(_request()))
    assert outcome.readiness == "drilling"
    assert len(transport.requests) == 2 and transport.requests[1].repair_errors

    with pytest.raises(RoleContractError):
        asyncio.run(service.review(_request(answer_transcript="Yes. No.")))
    with pytest.raises(PracticeReviewUnavailable):
        asyncio.run(PracticeReviewService(None, model="m").review(_request()))
